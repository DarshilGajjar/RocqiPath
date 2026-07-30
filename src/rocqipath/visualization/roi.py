"""Random tissue-ROI scoring, sampling, and sidecar persistence."""

from __future__ import annotations

import json
import os
import random
from typing import Any, Dict, List, Tuple

from PIL import Image

from rocqipath.core.logging import logger
from rocqipath.core.tissue import brightness_saturation_is_tissue

_ROI_SIDECAR_SUFFIX = "_random_roi_coords.json"
_ROI_COLORS = [
    "#0173B2",
    "#DE8F05",
    "#CC78BC",
    "#CA9161",
    "#56B4E9",
    "#029E73",
    "#ECE133",
    "#56B4E9",
    "#F8766D",
    "#00BA38",
]
_EDGE_MARGIN = 0.05
_TISSUE_BRIGHTNESS_THRESHOLD = 220
_TISSUE_SATURATION_THRESHOLD = 0.05
_TISSUE_MAX_ATTEMPTS = 200
_TISSUE_THUMB_SIZE = 64


def _score_crop(img: Image.Image, bbox: Tuple[int, int, int, int]) -> Tuple[float, float]:
    """Return (mean_brightness, mean_saturation) for a crop region.

    Uses a small thumbnail for speed — sufficient to distinguish tissue from
    blank background without loading the full high-res crop.

    Returns
    -------
        (mean_brightness, mean_saturation) both in [0, 1] range.
    """
    crop = img.crop(bbox)
    thumb = crop.resize((_TISSUE_THUMB_SIZE, _TISSUE_THUMB_SIZE), Image.Resampling.BILINEAR)

    grey = thumb.convert("L")
    brightness = sum(grey.getdata()) / (grey.width * grey.height * 255.0)

    hsv = thumb.convert("HSV")
    _, s, _ = hsv.split()
    saturation = sum(s.getdata()) / (s.width * s.height * 255.0)

    return brightness, saturation


def _is_tissue(brightness: float, saturation: float) -> bool:
    """Return True if the crop looks like tissue rather than blank background."""
    return brightness_saturation_is_tissue(
        brightness,
        saturation,
        brightness_threshold=_TISSUE_BRIGHTNESS_THRESHOLD,
        saturation_threshold=_TISSUE_SATURATION_THRESHOLD,
    )


def _random_roi_bbox(
    img: Image.Image,
    w: int,
    h: int,
    size: int,
    rng: random.Random,
) -> Tuple[int, int, int, int]:
    """Sample a random tissue-containing crop box inside the WSI.

    Candidate positions are drawn uniformly from the interior of the image
    (with an _EDGE_MARGIN inset). Each candidate is scored using a fast
    thumbnail brightness + saturation check. The first candidate that passes
    both tissue thresholds is returned.

    If no tissue crop is found within _TISSUE_MAX_ATTEMPTS tries the
    candidate with the lowest brightness (most tissue-like) seen so far is
    returned as a fallback, with a warning logged.
    """
    margin_x = max(int(w * _EDGE_MARGIN), size // 2)
    margin_y = max(int(h * _EDGE_MARGIN), size // 2)

    x_min = margin_x
    x_max = w - margin_x - size
    y_min = margin_y
    y_max = h - margin_y - size

    def _clamp_bbox(left: int, top: int) -> Tuple[int, int, int, int]:
        """Clamp a proposed crop box so it fits fully within the image bounds.

        Parameters
        ----------
        left, top : int
            Proposed top-left corner of a ``size`` x ``size`` crop box,
            possibly extending outside ``[0, w) x [0, h)`` (the enclosing
            function's image dimensions).

        Returns
        -------
        tuple of (int, int, int, int)
            ``(left, top, right, bottom)`` — the crop box shifted (not
            resized) so that ``right <= w`` and ``bottom <= h``. Same
            clamping logic as ``_region_bbox``'s local ``_clamp`` helper;
            duplicated here rather than shared since the two functions
            don't otherwise share a module-level scope.
        """
        right = min(w, left + size)
        bottom = min(h, top + size)
        left = max(0, right - size)
        top = max(0, bottom - size)
        return (left, top, right, bottom)

    if x_max <= x_min or y_max <= y_min:
        return _clamp_bbox(max(0, (w - size) // 2), max(0, (h - size) // 2))

    best_bbox = None
    best_brightness = 1.0  # lower is better (darker = more tissue)

    for attempt in range(1, _TISSUE_MAX_ATTEMPTS + 1):
        left = rng.randint(x_min, x_max)
        top = rng.randint(y_min, y_max)
        bbox = _clamp_bbox(left, top)

        brightness, saturation = _score_crop(img, bbox)

        if brightness < best_brightness:
            best_brightness = brightness
            best_bbox = bbox

        if _is_tissue(brightness, saturation):
            logger.debug(
                f"    Tissue crop found on attempt {attempt} "
                f"(brightness={brightness:.3f}, saturation={saturation:.3f})"
            )
            return bbox

    logger.warning(
        f"Could not find a tissue crop in {_TISSUE_MAX_ATTEMPTS} attempts "
        f"(best brightness={best_brightness:.3f}). "
        f"Using best candidate — consider adjusting _TISSUE_BRIGHTNESS_THRESHOLD."
    )
    return best_bbox


def _load_or_create_roi_sidecar(
    sidecar_path: str,
    img: Image.Image,
    w: int,
    h: int,
    zoom_sizes: List[Tuple[str, int]],
    n_rois: int,
    seed: int,
) -> Dict[str, Any]:
    """Return the ROI coordinate dictionary, loading from disk if it exists.

    When generating fresh ROIs, each candidate crop is tested against the
    tissue-detection thresholds in ``_score_crop`` / ``_is_tissue`` so that
    ROIs land on tissue rather than blank glass background.

    Args:
        img : the H&E PIL Image used for tissue scoring (read-only).
    """
    zoom_labels = [zl for zl, _ in zoom_sizes]

    if os.path.isfile(sidecar_path):
        with open(sidecar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if (
            data.get("seed") == seed
            and data.get("image_size") == [w, h]
            and set(data.get("rois", {}).keys()) == set(zoom_labels)
            and all(len(v) == n_rois for v in data["rois"].values())
        ):
            logger.info(f"Loaded existing ROI sidecar: {sidecar_path}")
            return data
        else:
            logger.warning("Existing ROI sidecar does not match current parameters — regenerating.")

    logger.info(
        f"Sampling tissue-aware ROIs "
        f"(brightness < {_TISSUE_BRIGHTNESS_THRESHOLD}, "
        f"saturation > {_TISSUE_SATURATION_THRESHOLD}, "
        f"max {_TISSUE_MAX_ATTEMPTS} attempts each)..."
    )
    rng = random.Random(seed)
    rois: Dict[str, List[Dict[str, Any]]] = {}
    for zoom_label, size in zoom_sizes:
        entries = []
        for idx in range(1, n_rois + 1):
            logger.info(f"  Sampling {zoom_label} ROI {idx}/{n_rois}...")
            bbox = _random_roi_bbox(img, w, h, size, rng)
            entries.append(
                {
                    "roi_id": f"roi_{idx:02d}",
                    "bbox": list(bbox),
                }
            )
        rois[zoom_label] = entries

    data = {
        "seed": seed,
        "image_size": [w, h],
        "rois": rois,
    }
    os.makedirs(os.path.dirname(os.path.abspath(sidecar_path)), exist_ok=True)
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Saved ROI sidecar: {sidecar_path}")
    return data


__all__ = [
    "_ROI_COLORS",
    "_ROI_SIDECAR_SUFFIX",
    "_score_crop",
    "_is_tissue",
    "_random_roi_bbox",
    "_load_or_create_roi_sidecar",
]
