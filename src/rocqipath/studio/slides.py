"""Local slide discovery and bounded thumbnail/tile reads."""

from __future__ import annotations

import hashlib
import io
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw

EXTENSIONS = {".tif", ".tiff", ".svs", ".ndpi", ".scn", ".mrxs", ".png", ".jpg", ".jpeg"}


def identifier(path):
    """Create an opaque deterministic ID from a canonical local path."""
    return hashlib.sha256(str(path).encode()).hexdigest()[:24]


def scan(store, path, demo=False):
    """Register a folder and up to 2,000 supported images beneath it."""
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Choose a folder containing slide images.")
    folder_id = identifier(root)
    count = 0
    truncated = False
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__"}]
        for name in sorted(files):
            file = Path(directory, name)
            if file.suffix.lower() not in EXTENSIONS or not file.resolve().is_relative_to(root):
                continue
            if count >= 2000:
                truncated = True
                break
            resolved = file.resolve()
            store.save("slide", {"id": identifier(resolved), "name": name, "path": str(resolved),
                "folder_id": folder_id, "relative": file.relative_to(root).as_posix(),
                "size": file.stat().st_size, "format": file.suffix[1:].upper(), "demo": demo})
            count += 1
        if truncated:
            break
    return store.save("folder", {"id": folder_id, "name": root.name, "path": str(root), "count": count, "demo": demo, "truncated": truncated})


def resolve_slide(store, slide_id):
    """Resolve only registered images still contained in their chosen folder."""
    slide = store.get("slide", slide_id)
    folder = store.get("folder", slide["folder_id"])
    path = Path(slide["path"]).resolve(strict=True)
    if not path.is_relative_to(Path(folder["path"]).resolve()):
        raise PermissionError("This image is outside its registered folder.")
    return path


def open_slide(path):
    """Use OpenSlide when supported and Pillow for ordinary bounded images."""
    try:
        import openslide
        return openslide.OpenSlide(str(path)), True
    except (ImportError, OSError):
        pass
    image = Image.open(path)
    if image.width * image.height > 100_000_000:
        image.close()
        raise ValueError("This large image needs an OpenSlide-compatible pyramid. Convert it to a pyramidal TIFF first.")
    return image, False


def info(path):
    """Return actual dimensions and available scanner metadata."""
    image, native = open_slide(path)
    try:
        width, height = image.dimensions if native else image.size
        properties = dict(image.properties) if native else {}
        return {"width": width, "height": height, "max_level": math.ceil(math.log2(max(width, height))),
            "tile_size": 256, "objective": properties.get("openslide.objective-power"),
            "mpp": properties.get("openslide.mpp-x"), "backend": "OpenSlide" if native else "Pillow",
            "levels": image.level_count if native else 1}
    finally:
        image.close()


def jpeg(path, level=None, x=0, y=0):
    """Render a thumbnail or one Deep Zoom tile without a full WSI canvas."""
    image, native = open_slide(path)
    try:
        if level is None:
            if native:
                region = image.get_thumbnail((720, 520))
            else:
                image.thumbnail((720, 520))
                region = image.convert("RGB")
        elif native:
            from openslide.deepzoom import DeepZoomGenerator
            generator = DeepZoomGenerator(image, tile_size=256, overlap=0, limit_bounds=False)
            if level < 0 or level >= generator.level_count:
                raise ValueError("Invalid tile level")
            columns, rows = generator.level_tiles[level]
            if not 0 <= x < columns or not 0 <= y < rows:
                raise ValueError("Invalid tile coordinates")
            region = generator.get_tile(level, (x, y))
        else:
            max_level = math.ceil(math.log2(max(image.size)))
            if not 0 <= level <= max_level:
                raise ValueError("Invalid tile level")
            scale = 2 ** (max_level - level)
            left, top = x * 256 * scale, y * 256 * scale
            if x < 0 or y < 0 or left >= image.width or top >= image.height:
                raise ValueError("Invalid tile coordinates")
            region = image.crop((left, top, min(left + 256 * scale, image.width), min(top + 256 * scale, image.height)))
            region.thumbnail((256, 256))
        rgb = Image.new("RGB", region.size, "white")
        if region.mode == "RGBA":
            rgb.paste(region, mask=region.getchannel("A"))
        else:
            rgb.paste(region.convert("RGB"))
        output = io.BytesIO()
        rgb.save(output, "JPEG", quality=85)
        return output.getvalue()
    finally:
        image.close()


def create_demo(store):
    """Generate clearly synthetic tissue-like images for local exploration."""
    import random
    root = store.root / "demo-slides"
    root.mkdir(exist_ok=True)
    for index, (name, color) in enumerate([("Demo_HE", (132, 61, 129)), ("Demo_DAB", (119, 77, 37)), ("Demo_section", (141, 64, 114))]):
        path = root / f"{name}.tif"
        if path.exists():
            continue
        rng = random.Random(42 + index)
        image = Image.new("RGB", (2048, 1536), (251, 247, 244))
        draw = ImageDraw.Draw(image)
        for _ in range(180):
            x, y = rng.randrange(200, 1848), rng.randrange(180, 1356)
            radius = rng.randrange(50, 180)
            draw.ellipse((x-radius, y-radius//2, x+radius, y+radius//2), fill=(238+rng.randrange(12), 203+rng.randrange(25), 218+rng.randrange(20)))
        for _ in range(11000):
            x, y = rng.randrange(100, 1948), rng.randrange(100, 1436)
            if ((x-1024)/920)**2 + ((y-768)/660)**2 > 1 or rng.random() < 0.1:
                continue
            radius = rng.randrange(2, 7)
            shade = tuple(min(255, c+rng.randrange(35)) for c in color)
            draw.ellipse((x-radius, y-radius//2, x+radius, y+radius), fill=shade)
        image.save(path, compression="tiff_lzw")
    return scan(store, root, demo=True)
