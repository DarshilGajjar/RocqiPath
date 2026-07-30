"""Image read/write helpers with intentionally function-local optional imports.

Keeping OpenCV inside the functions preserves lightweight ``rocqipath.utils``
imports. Do not move these imports to module scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def imread_rgb(path: Path) -> Any | None:
    """Read an image with OpenCV and return an RGB array, or ``None``."""
    import cv2 as cv

    bgr = cv.imread(str(path))
    if bgr is None:
        return None
    return cv.cvtColor(bgr, cv.COLOR_BGR2RGB)


def imwrite_rgb(path: Path, rgb: Any) -> None:
    """Write an RGB array with OpenCV, creating its parent directory."""
    import cv2 as cv

    path.parent.mkdir(parents=True, exist_ok=True)
    cv.imwrite(str(path), cv.cvtColor(rgb, cv.COLOR_RGB2BGR))


def save_tif(region: Any, tif_path: Path, cfg: Any) -> None:
    """Write a pyvips region with the extraction config's TIFF settings."""
    region.tiffsave(
        str(tif_path),
        tile=cfg.tif_tile,
        pyramid=cfg.tif_pyramid,
        compression=cfg.tif_compression,
        Q=cfg.tif_quality,
    )


def save_preview(region: Any, preview_path: Path, preview_scale: float) -> None:
    """Write a fixed-quality downscaled JPEG preview of a pyvips region."""
    region.resize(preview_scale).jpegsave(str(preview_path), Q=85, strip=True)


__all__ = ["imread_rgb", "imwrite_rgb", "save_preview", "save_tif"]
