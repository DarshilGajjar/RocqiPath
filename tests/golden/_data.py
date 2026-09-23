"""Deterministic synthetic inputs for golden workflow tests.

Every builder is seeded so repeated runs produce byte-identical inputs.
Images are ordinary RGB TIFF/PNG files read through the Pillow fallback,
so no scanner files are needed. Source magnification is always 20x.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

SOURCE_MAG = 20.0
HE_TISSUE = (190, 110, 160)
DAB_BROWN = (120, 70, 30)
IHC_BACKGROUND = (175, 185, 215)


def _save(path: Path, rgb: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb.astype(np.uint8), mode="RGB").save(path)
    return path


def _save_pyramid(path: Path, rgb: np.ndarray) -> Path:
    """Save a tiled pyramidal TIFF that OpenSlide opens as a generic TIFF."""
    import pyvips

    path.parent.mkdir(parents=True, exist_ok=True)
    h, w, _ = rgb.shape
    image = pyvips.Image.new_from_memory(np.ascontiguousarray(rgb).tobytes(), w, h, 3, "uchar")
    image.tiffsave(str(path), tile=True, tile_width=256, tile_height=256, pyramid=True, compression="lzw")
    return path


def _noise(rng: np.random.Generator, shape, amplitude: int = 12) -> np.ndarray:
    return rng.integers(-amplitude, amplitude + 1, size=shape)


def _ellipse_mask(h: int, w: int, cy: float, cx: float, ry: float, rx: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    return ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 <= 1.0


def tissue_rgb(h: int, w: int, blobs, color=HE_TISSUE, seed: int = 0) -> np.ndarray:
    """White slide with textured tissue ellipses ``(cy, cx, ry, rx)``."""
    rng = np.random.default_rng(seed)
    rgb = np.full((h, w, 3), 245, dtype=np.int32)
    for cy, cx, ry, rx in blobs:
        mask = _ellipse_mask(h, w, cy, cx, ry, rx)
        rgb[mask] = color
    tissue = rgb[..., 0] < 240
    rgb[tissue] += _noise(rng, (int(tissue.sum()), 3))
    return np.clip(rgb, 0, 255).astype(np.uint8)


def dab_rgb(h: int, w: int, n_cells: int, seed: int = 0) -> np.ndarray:
    """IHC-like tile: bluish tissue with ``n_cells`` brown round cells."""
    rng = np.random.default_rng(seed)
    rgb = tissue_rgb(h, w, [(h / 2, w / 2, h * 0.45, w * 0.45)], IHC_BACKGROUND, seed)
    rgb = rgb.astype(np.int32)
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(n_cells):
        cy = rng.uniform(h * 0.2, h * 0.8)
        cx = rng.uniform(w * 0.2, w * 0.8)
        r = rng.uniform(6, 9)
        dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        cell = dist <= r
        # Dark core fading to a lighter rim, as in real DAB staining.
        shade = (0.55 + 0.6 * dist[cell] / r)[:, None]
        rgb[cell] = np.array(DAB_BROWN) * shade
    return np.clip(rgb, 0, 255).astype(np.uint8)


def make_tissue_slides(root: Path) -> Path:
    """Two slides, each with two separated tissue regions."""
    src = root / "tissue_in"
    _save(src / "slideA.tif", tissue_rgb(1200, 1600, [(400, 450, 250, 300), (800, 1200, 250, 250)], seed=1))
    _save(src / "slideB.tif", tissue_rgb(1200, 1600, [(600, 800, 400, 500)], seed=2))
    return src


def make_tma(root: Path) -> Path:
    """One TMA block: H&E and CD8 slides with a 2x2 grid of round cores."""
    src = root / "tma_in"
    cores = [(400, 400, 220, 220), (400, 1200, 220, 220), (1200, 400, 220, 220), (1200, 1200, 220, 220)]
    _save(src / "TMA01_HE.tif", tissue_rgb(1600, 1600, cores, seed=3))
    _save(src / "TMA01_CD8.tif", tissue_rgb(1600, 1600, cores, IHC_BACKGROUND, seed=4))
    return src


def make_patch_pairs(root: Path) -> dict:
    """Reference slide plus aligned CD8 slide in the patch-extraction layout."""
    ref_root = root / "patch_ref"
    aligned_root = root / "patch_aligned"
    blobs = [(128, 128, 110, 110)]
    _save(ref_root / "Sample_0001_he.tif", tissue_rgb(256, 256, blobs, seed=5))
    _save(
        aligned_root / "CD8" / "Sample_0001_he" / "aligned_cd8.ome.tiff",
        tissue_rgb(256, 256, blobs, IHC_BACKGROUND, seed=6),
    )
    return {"reference_root": ref_root, "aligned_root": aligned_root}


def make_reversible(root: Path) -> dict:
    """Legacy ReversiblePatchExtractor layout: <biomarker>/he/Sample_NNNN_he.tif."""
    he_root = root / "rev_he"
    aligned_root = root / "rev_aligned"
    blobs = [(128, 128, 110, 110)]
    _save(he_root / "CD8" / "he" / "Sample_0001_he.tif", tissue_rgb(256, 256, blobs, seed=7))
    _save(
        aligned_root / "CD8" / "Sample_0001_he" / "aligned_cd8.ome.tiff",
        tissue_rgb(256, 256, blobs, IHC_BACKGROUND, seed=8),
    )
    return {"he_root": he_root, "aligned_root": aligned_root}


def make_stain_patches(root: Path) -> Path:
    """Folder of small H&E-like patches under an ``he`` stain folder."""
    src = root / "stain_in" / "he"
    for i in range(3):
        rgb = tissue_rgb(128, 128, [(64, 64, 60, 60)], (180 - 10 * i, 100 + 5 * i, 150), seed=10 + i)
        _save(src / f"patch_{i}.png", rgb)
    return src.parent


def make_count_slides(root: Path) -> dict:
    """Ground-truth and predicted DAB slides with known cell counts."""
    src = root / "count_in"
    gt = _save(src / "case_gt.tif", dab_rgb(1024, 1024, 25, seed=20))
    pred = _save(root / "count_pred" / "case_pred.tif", dab_rgb(1024, 1024, 18, seed=21))
    return {"dir": src, "gt": gt, "pred": pred}


def make_overlay_case(root: Path) -> Path:
    """One case with HE and CD8 marker folders sharing patch names."""
    case = root / "overlay_in" / "case01"
    for i in range(2):
        _save(case / "HE" / f"p{i}.png", tissue_rgb(128, 128, [(64, 64, 55, 55)], seed=30 + i))
        _save(case / "CD8" / f"p{i}.png", dab_rgb(128, 128, 4, seed=40 + i))
    return case


def make_compare_slides(root: Path) -> dict:
    """H&E, ground-truth IHC and predicted IHC slides of equal size."""
    src = root / "compare_in"
    return {
        "he": _save(src / "he.tif", tissue_rgb(800, 800, [(400, 400, 300, 300)], seed=50)),
        "gt": _save(src / "gt.tif", dab_rgb(800, 800, 30, seed=51)),
        "pred": _save(src / "pred.tif", dab_rgb(800, 800, 30, seed=52)),
    }


def make_alignment_pair(root: Path) -> Path:
    """One H&E/CD8 pair; the moving slide is a shifted copy of the reference."""
    src = root / "align_in"
    rng = np.random.default_rng(60)
    base = tissue_rgb(1024, 1024, [(512, 480, 330, 280), (380, 700, 120, 90)], seed=61).astype(np.int32)
    texture = rng.integers(-40, 41, size=(64, 64, 3))
    texture = np.kron(texture, np.ones((16, 16, 1), dtype=np.int32))
    tissue = base[..., 0] < 240
    base[tissue] += texture[tissue]
    base = np.clip(base, 0, 255).astype(np.uint8)
    moving = np.full_like(base, 245)
    moving[20:, 30:] = base[:-20, :-30]
    _save_pyramid(src / "CD8" / "he" / "case01_HE.tif", base)
    _save_pyramid(src / "CD8" / "cd8" / "case01_CD8.tif", moving)
    return src
