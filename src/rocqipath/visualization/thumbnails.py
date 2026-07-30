"""Export whole-slide thumbnails in common image formats."""

from __future__ import annotations

import os
from typing import List, Optional

from rocqipath.core.logging import logger
from rocqipath.core.output import OutputLayout
from rocqipath.utils import list_wsi_files


def export_wsi_thumbnails(
    input_dir: str,
    output_dir: str,
    *,
    wsi_files: Optional[List[str]] = None,
    max_dim: int = 5000,
    fmt: str = "png",
    jpeg_quality: int = 95,
    overwrite: bool = False,
) -> List[str]:
    """Export WSI thumbnails at a configurable resolution and format."""
    try:
        import openslide
    except ImportError:
        raise RuntimeError("openslide-python is required for WSI thumbnail export.")

    layout = OutputLayout(output_dir)
    fmt = fmt.lower()
    ext = "jpg" if fmt in ("jpeg", "jpg") else ("tif" if fmt in ("tiff", "tif") else "png")

    all_files = list_wsi_files(input_dir)
    files_to_export = wsi_files if wsi_files else all_files
    if not files_to_export:
        logger.warning(f"No WSI files found in {input_dir}")
        return []

    exported: List[str] = []
    for wsi_file in files_to_export:
        wsi_path = os.path.join(input_dir, wsi_file)
        base = os.path.splitext(os.path.basename(wsi_path))[0]
        out_path = str(layout.item_dir("visualization", base) / f"{base}_export.{ext}")

        if os.path.exists(out_path) and not overwrite:
            logger.info(f"Exists (skip): {out_path}")
            exported.append(out_path)
            continue

        try:
            slide = openslide.OpenSlide(wsi_path)
            width, height = slide.dimensions
            if width >= height:
                thumb_width, thumb_height = max_dim, int(max_dim * height / width)
            else:
                thumb_width, thumb_height = (
                    int(max_dim * width / height),
                    max_dim,
                )

            thumb = slide.get_thumbnail((thumb_width, thumb_height)).convert("RGB")
            if ext == "jpg":
                thumb.save(out_path, quality=jpeg_quality)
            else:
                thumb.save(out_path)
            slide.close()

            logger.info(f"Exported: {out_path}")
            exported.append(out_path)
        except Exception as exc:
            logger.error(f"Export failed for {wsi_path}: {exc}")

    return exported


__all__ = ["export_wsi_thumbnails"]
