"""Thumbnail loading and contour detection for extraction pipelines."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    import pyvips  # noqa: F401

    _PYVIPS_AVAILABLE = True
except (ImportError, OSError):
    _PYVIPS_AVAILABLE = False

from rocqipath.core.logging import logger
from rocqipath.extraction.engine import _resolve_vips_magnification
from rocqipath.utils.geometry import sort_contours_spatially as _sort_contours_spatially
from rocqipath.utils.vips import open_vips_pyramid_level as _open_vips_pyramid_level
from rocqipath.utils.vips import vips_to_numpy_rgb as _vips_to_numpy_rgb


def _load_thumbnail(
    wsi_path: Path,
    level: Optional[int] = None,
    *,
    target_magnification: float = 1.25,
    source_magnification: Optional[float] = None,
) -> np.ndarray:
    """Load a downsampled thumbnail of a whole-slide image via pyvips.

    Attempts, in order, to open the requested pyramid level using two
    different pyvips access syntaxes (some formats expose pyramid levels
    as ``[level=N]``, others as ``[page=N]``), and falls back to loading
    the full-resolution image and resizing it in-memory if neither
    succeeds.

    Parameters
    ----------
    wsi_path : Path
        Path to the whole-slide image file.
    level : int
        Requested pyramid level, where level 0 is full resolution and
        each subsequent level is (conventionally) half the linear
        resolution of the previous one.

    Returns
    -------
    numpy.ndarray
        The thumbnail as a ``(height, width, 3)`` ``uint8`` RGB array
        (via :func:`_vips_to_numpy_rgb`).

    Raises
    ------
    ImportError
        If the optional ``pyvips`` dependency is not installed.

    Notes
    -----
    Resolution order:

    1. Try ``f"{path}[level={level}]"`` (common for SVS and similar
       formats).
    2. Try ``f"{path}[page={level}]"`` (common for multi-page TIFF-based
       formats).
    3. If both raise :class:`pyvips.Error`, log a warning and fall back
       to opening the full-resolution image and resizing it by
       ``1 / (2 ** level)`` — this is slow (it loads the entire base
       resolution into memory) but guarantees a result for formats whose
       pyramid structure pyvips can't address directly.

    All three paths ultimately return through :func:`_vips_to_numpy_rgb`,
    so the returned array is always RGB-only regardless of the source
    image's band count.
    """
    if not _PYVIPS_AVAILABLE:
        raise ImportError("pyvips is required. pip install rocqipath[extraction]")
    path = Path(wsi_path)
    base = _open_vips_pyramid_level(path, 0)

    if level is not None:
        try:
            image = _open_vips_pyramid_level(path, level)
        except Exception:
            logger.warning(f"Level {level} unavailable for {path.name}; resizing level 0.")
            image = base.resize(1 / (2**level))
        return _vips_to_numpy_rgb(image)

    base_mag, source = _resolve_vips_magnification(base, source_magnification)
    if target_magnification > base_mag:
        raise ValueError(
            f"Detection magnification {target_magnification:g}x exceeds "
            f"{path.name}'s base magnification {base_mag:g}x"
        )

    candidates = [(0, base)]
    for candidate_level in range(1, 12):
        try:
            candidate = _open_vips_pyramid_level(path, candidate_level)
        except Exception:
            break
        if (
            candidate.width == candidates[-1][1].width
            and candidate.height == candidates[-1][1].height
        ):
            break
        candidates.append((candidate_level, candidate))

    def native_mag(item: Tuple[int, Any]) -> float:
        """Estimate a candidate level's objective magnification from width."""
        return base_mag * (item[1].width / base.width)

    chosen_level, chosen = min(
        candidates, key=lambda item: abs(math.log(native_mag(item) / target_magnification))
    )
    chosen_mag = native_mag((chosen_level, chosen))
    resize = target_magnification / chosen_mag
    if not math.isclose(resize, 1.0, rel_tol=1e-6):
        chosen = chosen.resize(resize)
    logger.debug(
        f"pyvips | {path.name} | objective={base_mag:g}x ({source}) | "
        f"detection={target_magnification:g}x | level={chosen_level} | "
        f"size={chosen.width}x{chosen.height}"
    )
    return _vips_to_numpy_rgb(chosen)


def _detect_regions(
    thumbnail: np.ndarray,
    min_area_fraction: float,
    only_circles: bool = False,
    min_circularity: float = 0.0,
) -> List[Dict[str, float]]:
    """Detect tissue regions on a thumbnail via Otsu thresholding.

    Parameters
    ----------
    thumbnail : numpy.ndarray
        A ``(height, width, 3)`` RGB thumbnail image.
    min_area_fraction : float
        Minimum contour area as a fraction of thumbnail area.
    only_circles : bool, optional
        Whether to reject contours below ``min_circularity``.
    min_circularity : float, optional
        Minimum value of ``4π * area / perimeter²``.

    Returns
    -------
    list of dict
        Relative bounding boxes in reading order.
    """
    h, w = thumbnail.shape[:2]
    gray = cv2.cvtColor(thumbnail, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (13, 13), 0)
    _, thr = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = h * w * min_area_fraction
    valid: List = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        if only_circles:
            peri = cv2.arcLength(cnt, True)
            if peri == 0:
                continue
            if (4 * np.pi * area) / (peri**2) < min_circularity:
                continue
        valid.append(cnt)
    rel_boxes: List[Dict[str, float]] = []
    for cnt in _sort_contours_spatially(valid):
        x, y, bw, bh = cv2.boundingRect(cnt)
        rel_boxes.append({"rx": x / w, "ry": y / h, "rw": bw / w, "rh": bh / h})
    return rel_boxes
