#!/usr/bin/env python3
"""
rocqipath.visualization.wsi_compare
=====================================
Publication-quality side-by-side whole-slide image comparison figures.

Generates high-resolution ground-truth-vs-prediction (or any two-image)
comparison figures with scale bars, colourblind-safe annotations, and
professional figure formatting — suitable for papers, posters, and
reports, as opposed to :mod:`rocqipath.visualization.visualization`'s
quick exploratory QC plots.

Also runnable as a standalone script::

    python -m rocqipath.visualization.wsi_compare --help

Uses its own self-contained banner/logging setup (via ``loguru``,
independent of :mod:`rocqipath.logger`) since it predates the unified
logging system and is also usable outside the rest of the package.

WSI Visualization Module for RocqiPath — PUBLICATION-QUALITY EDITION
Generates high-resolution side-by-side comparisons with scale bars,
colorblind-safe annotations, and professional figure formatting.
"""

import os
import sys
import json
import random
import argparse
import shutil
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import to_rgba
from typing import Optional, List, Tuple, Dict, Any
from loguru import logger
from PIL import Image, ImageDraw, PngImagePlugin, ImageFont

# WARNING: raising this reduces Pillow's protection against malicious decompression bombs.
PngImagePlugin.MAX_TEXT_CHUNK = 64 * 1024 * 1024
# Essential for loading massive WSIs without raising DecompressionBombError
Image.MAX_IMAGE_PIXELS = None


# ============================================================================
# PUBLICATION-QUALITY COLOR PALETTES
# ============================================================================
COLORBLIND_SAFE_PALETTE = [
    "#0173B2",  # Blue
    "#DE8F05",  # Orange
    "#CC78BC",  # Magenta
    "#CA9161",  # Brown
    "#56B4E9",  # Light blue
    "#029E73",  # Green
    "#ECE133",  # Yellow
    "#56B4E9",  # Cyan
    "#F8766D",  # Red
    "#00BA38",  # Bright green
]

# Publication-grade grayscale for structure/labels
GRAYSCALE_PALETTE = [
    "#000000",  # Black (text, main stroke)
    "#404040",  # Dark gray (secondary)
    "#808080",  # Medium gray (tertiary)
    "#C0C0C0",  # Light gray (borders)
    "#FFFFFF",  # White (background)
]


# ============================================================================
# UNIVERSAL LOGGING + BANNER SETUP
# ============================================================================
def _build_banner(tool_name: str, subtitle: str = "") -> str:
    """Build a centred, boxed ASCII banner string for startup logging.

    Parameters
    ----------
    tool_name : str
        Title shown on the banner's first content line.
    subtitle : str, optional
        Optional second content line (e.g. a mode or version string).
        Omitted from the banner entirely when empty.

    Returns
    -------
    str
        A multi-line string: a box-drawing-character border surrounding
        ``tool_name``, ``subtitle`` (if given), and a fixed
        ``"Author: Darshil Gajjar"`` line — each line horizontally
        centred within the box, and the whole box horizontally centred
        within the current terminal width (detected via
        :func:`shutil.get_terminal_size`, falling back to 80 columns if
        that can't be determined). Prefixed and suffixed with a newline
        for spacing when printed.

    Notes
    -----
    This is a self-contained plain-text banner, independent of the
    Rich-based banner in :func:`rocqipath.logger.print_banner` — this
    module predates the unified logging system and remains usable
    standalone.
    """
    inner_width = 54
    lines = [
        "╔" + "═" * inner_width + "╗",
        "║" + tool_name.center(inner_width) + "║",
    ]
    if subtitle:
        lines.append("║" + subtitle.center(inner_width) + "║")
    lines.extend(
        [
            "║" + "Author: Darshil Gajjar".center(inner_width) + "║",
            "╚" + "═" * inner_width + "╝",
        ]
    )
    term_width = shutil.get_terminal_size(fallback=(80, 24)).columns
    return "\n" + "\n".join(line.center(term_width) for line in lines) + "\n"


def configure_logging(
    tool_name: str = "Digital Pathology Pipeline",
    subtitle: str = "",
    save_dir: Optional[str] = None,
) -> None:
    """Reset and configure this module's loguru sinks, printing a startup banner.

    Parameters
    ----------
    tool_name : str, optional
        Title shown in the startup banner (see :func:`_build_banner`).
        Defaults to ``"Digital Pathology Pipeline"``.
    subtitle : str, optional
        Optional subtitle line for the banner. Omitted from the banner
        when empty.
    save_dir : str, optional
        If given, an additional file sink is created inside this
        directory (created if it doesn't exist), logging at DEBUG level
        to ``execution_log.log`` with automatic rotation at 10 MB and up
        to 5 retained rotated files. When omitted (``None``), logging
        goes only to stdout.

    Notes
    -----
    Calls ``logger.remove()`` first, clearing any previously configured
    sinks on the module-level ``loguru`` logger — so calling this
    function replaces rather than adds to prior configuration. The
    stdout sink logs at INFO level with a colourised timestamp/level/message
    format. After configuring sinks, logs the banner produced by
    :func:`_build_banner` at INFO level.
    """
    logger.remove()
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<white>{message}</white>"
        ),
        level="INFO",
        colorize=True,
    )
    if save_dir is not None:
        os.makedirs(save_dir, exist_ok=True)
        log_path = os.path.join(save_dir, "execution_log.log")
        logger.add(
            log_path,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
            level="DEBUG",
            rotation="10 MB",
            retention=5,
        )
    logger.info(_build_banner(tool_name, subtitle))


# ============================================================================
# MANIFEST READER
# ============================================================================
def _load_manifest(manifest_path: str) -> dict:
    """Load and validate a case manifest written by wsi_reconstruction.py."""
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    required_keys = {"case_id", "model", "split", "wsi_dir", "stains"}
    missing = required_keys - manifest.keys()
    if missing:
        raise ValueError(f"Manifest is missing required keys: {missing}")
    required_stains = {"gt_he", "gt_ihc", "prediction_ihc"}
    missing_stains = required_stains - manifest["stains"].keys()
    if missing_stains:
        raise ValueError(
            f"Manifest stains block is incomplete. Missing: {missing_stains}. "
            f"Have you run wsi_reconstruction.py for all three stain types?"
        )
    return manifest


# ============================================================================
# REGION HELPERS
# ============================================================================
VALID_REGIONS: Tuple[str, ...] = (
    "center",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
)

_REGION_LABELS: Dict[str, str] = {
    "center": "Center",
    "top_left": "Top-Left",
    "top_right": "Top-Right",
    "bottom_left": "Bottom-Left",
    "bottom_right": "Bottom-Right",
}

_EDGE_MARGIN = 0.05

# Minimum tissue coverage required for a named-region crop (0.0–1.0).
# 0.50 = reject any crop where > 50 % of pixels are background/glass.
REGION_TISSUE_THRESHOLD: float = 0.50

# Search parameters: how far from the nominal anchor to hunt for tissue.
REGION_SEARCH_RADIUS_FRAC: float = 0.25  # up to 25 % of image dimension
REGION_SEARCH_STEP_FRAC: float = 0.02  # step 2 % per iteration

# Thumbnail size for fast tissue scoring during region search
_REGION_THUMB_SIZE: int = 64


def _tissue_fraction(img: Image.Image, bbox: Tuple[int, int, int, int]) -> float:
    """
    Return the fraction of pixels in *bbox* that look like tissue (0.0-1.0).

    A pixel is tissue if it is darker than _TISSUE_BRIGHTNESS_THRESHOLD
    AND has saturation above _TISSUE_SATURATION_THRESHOLD.
    Evaluation is done on a small thumbnail for speed.
    """
    crop = img.crop(bbox)
    thumb = crop.resize((_REGION_THUMB_SIZE, _REGION_THUMB_SIZE), Image.Resampling.BILINEAR)

    grey_arr = list(thumb.convert("L").getdata())
    _, s, _ = thumb.convert("HSV").split()
    sat_arr = list(s.getdata())

    n_pixels = len(grey_arr)
    n_tissue = sum(
        1
        for g, s in zip(grey_arr, sat_arr)
        if g < _TISSUE_BRIGHTNESS_THRESHOLD and s > (_TISSUE_SATURATION_THRESHOLD * 255)
    )
    return n_tissue / n_pixels if n_pixels > 0 else 0.0


def _region_bbox(
    w: int,
    h: int,
    size: int,
    region: str,
    img: Optional[Image.Image] = None,
) -> Tuple[int, int, int, int]:
    """
    Return a tissue-containing crop box for a named region.

    Searches outward from the nominal anchor toward the image interior until
    a crop with >= REGION_TISSUE_THRESHOLD tissue coverage is found.
    Falls back to the best-coverage position if the threshold is never met.

    img is optional — when None the nominal anchor is returned immediately
    (backward-compatible with any callers that omit it).
    """

    def _clamp(left: int, top: int) -> Tuple[int, int, int, int]:
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
            resized) so that ``right <= w`` and ``bottom <= h``, while
            keeping ``right - left == size`` and ``bottom - top == size``
            wherever possible (i.e. the crop box always has the
            requested dimensions unless the image itself is smaller than
            ``size``, in which case ``left``/``top`` clamp to ``0``).
        """
        right = min(w, left + size)
        bottom = min(h, top + size)
        left = max(0, right - size)
        top = max(0, bottom - size)
        return (left, top, right, bottom)

    margin_x = int(w * _EDGE_MARGIN)
    margin_y = int(h * _EDGE_MARGIN)
    half = size // 2

    anchors = {
        "center": (w // 2, h // 2),
        "top_left": (margin_x + half, margin_y + half),
        "top_right": (w - margin_x - half, margin_y + half),
        "bottom_left": (margin_x + half, h - margin_y - half),
        "bottom_right": (w - margin_x - half, h - margin_y - half),
    }
    if region not in anchors:
        raise ValueError(f"Unknown region '{region}'. Valid choices: {list(anchors)}")

    cx0, cy0 = anchors[region]
    nominal = _clamp(cx0 - half, cy0 - half)

    # No image → return nominal (backward-compatible)
    if img is None:
        return nominal

    # Each region searches toward the image interior to avoid the glass edge
    direction_map = {
        "center": [(+1, 0), (-1, 0), (0, +1), (0, -1), (+1, +1), (-1, +1), (+1, -1), (-1, -1)],
        "top_left": [(+1, +1)],
        "top_right": [(-1, +1)],
        "bottom_left": [(+1, -1)],
        "bottom_right": [(-1, -1)],
    }

    step_x = max(1, int(w * REGION_SEARCH_STEP_FRAC))
    step_y = max(1, int(h * REGION_SEARCH_STEP_FRAC))
    max_dx = int(w * REGION_SEARCH_RADIUS_FRAC)
    max_dy = int(h * REGION_SEARCH_RADIUS_FRAC)

    # Build all candidate positions sorted by distance from anchor (nearest first)
    seen: set = set()
    candidates: List[Tuple[float, Tuple[int, int, int, int]]] = []

    for dx_sign, dy_sign in direction_map[region]:
        dx = 0
        while dx <= max_dx:
            dy = 0
            while dy <= max_dy:
                cx = cx0 + dx_sign * dx
                cy = cy0 + dy_sign * dy
                bbox = _clamp(cx - half, cy - half)
                if bbox not in seen:
                    seen.add(bbox)
                    candidates.append(((dx**2 + dy**2) ** 0.5, bbox))
                dy += step_y
            dx += step_x

    candidates.sort(key=lambda x: x[0])

    best_frac: float = -1.0
    best_bbox = nominal

    for _, bbox in candidates:
        frac = _tissue_fraction(img, bbox)
        if frac > best_frac:
            best_frac = frac
            best_bbox = bbox
        if frac >= REGION_TISSUE_THRESHOLD:
            logger.debug(f"[{region}] accepted at tissue={frac:.1%}  bbox={bbox}")
            return bbox

    logger.warning(
        f"[{region}] No crop reached {REGION_TISSUE_THRESHOLD:.0%} tissue "
        f"({len(candidates)} positions searched, best={best_frac:.1%}). "
        f"Using best available. Lower REGION_TISSUE_THRESHOLD or raise "
        f"REGION_SEARCH_RADIUS_FRAC if this happens frequently."
    )
    return best_bbox


# ============================================================================
# RANDOM ROI HELPERS
# ============================================================================

# Sidecar filename suffix — stored next to the annotated full-view figure
_ROI_SIDECAR_SUFFIX = "_random_roi_coords.json"

# Colorblind-safe distinct colours for up to 10 ROIs
_ROI_COLORS = COLORBLIND_SAFE_PALETTE[:10]


# Tissue detection thresholds.
# A crop is accepted as tissue if it passes BOTH checks:
#   1. Mean brightness (grayscale) is below _TISSUE_BRIGHTNESS_THRESHOLD
#      — white background pixels are close to 255; tissue is darker.
#   2. Mean saturation (HSV) is above _TISSUE_SATURATION_THRESHOLD
#      — glass background is near-grey; H&E/IHC tissue has colour.
_TISSUE_BRIGHTNESS_THRESHOLD: int = 220  # 0-255; reject if mean grey >= this
_TISSUE_SATURATION_THRESHOLD: float = 0.05  # 0-1;   reject if mean sat  <= this
# Maximum candidate draws before giving up and returning the best seen so far
_TISSUE_MAX_ATTEMPTS: int = 200
# Thumbnail side length used for fast tissue scoring (pixels)
_TISSUE_THUMB_SIZE: int = 64


def _score_crop(img: Image.Image, bbox: Tuple[int, int, int, int]) -> Tuple[float, float]:
    """Return (mean_brightness, mean_saturation) for a crop region.

    Uses a small thumbnail for speed — sufficient to distinguish tissue from
    blank background without loading the full high-res crop.

    Returns:
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
    return (
        brightness <= _TISSUE_BRIGHTNESS_THRESHOLD / 255.0
        and saturation >= _TISSUE_SATURATION_THRESHOLD
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


# ============================================================================
# ANNOTATION HELPERS
# ============================================================================


def _add_scale_bar(
    img: Image.Image,
    microns: int,
    microns_per_pixel: float,
    location: str = "bottom_left",
    thickness: int = None,
) -> Image.Image:
    """Add a calibrated scale bar to the image.

    The scale bar length is computed from the physical pixel size of the crop
    (microns_per_pixel), which is derived from the WSI's native resolution and
    the zoom level — NOT from the output DPI.  This ensures the scale bar
    represents the correct tissue length regardless of figure DPI.

    Args:
        img               : PIL Image to annotate (the crop, in WSI pixels).
        microns           : tissue length the scale bar represents (e.g. 100, 500).
        microns_per_pixel : physical size of one WSI pixel in microns (e.g. 0.25 for 40×).
        location          : corner placement — "bottom_left", "bottom_right",
                            "top_left", or "top_right".
        thickness         : stroke width in pixels (auto-scaled to image width if None).

    Returns:
        Annotated PIL Image (original unchanged).
    """
    if thickness is None:
        thickness = max(2, int(img.width * 0.006))

    # Number of WSI pixels that span `microns` of tissue
    bar_length_px = int(microns / microns_per_pixel)
    # Cap at 40 % of image width so it never dominates the panel
    bar_length_px = min(bar_length_px, int(img.width * 0.40))
    bar_length_px = max(bar_length_px, 20)  # Minimum readable length

    font_size = max(28, int(img.width * 0.055))  # much larger — readable at print DPI
    margin = max(15, int(img.width * 0.03))
    tick_h = thickness * 3
    # Reserve space for bar + ticks + text + gap so nothing clips at the bottom
    vertical_space_needed = tick_h + font_size + 30

    locations_map = {
        "bottom_left": lambda w, h: (margin, h - margin - vertical_space_needed),
        "bottom_right": lambda w, h: (
            w - margin - bar_length_px,
            h - margin - vertical_space_needed,
        ),
        "top_left": lambda w, h: (margin, margin),
        "top_right": lambda w, h: (w - margin - bar_length_px, margin),
    }
    if location not in locations_map:
        location = "bottom_left"

    x, y = locations_map[location](img.width, img.height)
    # Clamp so the bar never starts off-image
    x = max(0, min(x, img.width - bar_length_px))
    y = max(0, min(y, img.height - vertical_space_needed))

    annotated = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(annotated)

    # Horizontal bar
    draw.line(
        [(x, y), (x + bar_length_px, y)],
        fill=(255, 255, 255, 255),
        width=thickness,
    )
    # Vertical end-ticks
    draw.line(
        [(x, y - tick_h // 2), (x, y + tick_h // 2)], fill=(255, 255, 255, 255), width=thickness
    )
    draw.line(
        [(x + bar_length_px, y - tick_h // 2), (x + bar_length_px, y + tick_h // 2)],
        fill=(255, 255, 255, 255),
        width=thickness,
    )

    label_text = f"{microns} µm"
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = x + (bar_length_px - text_width) // 2
    text_y = y + tick_h + 8

    # Draw a solid dark rounded-rectangle background behind the text
    pad_x, pad_y = max(6, font_size // 5), max(4, font_size // 8)
    bg_x0 = text_x - pad_x
    bg_y0 = text_y - pad_y
    bg_x1 = text_x + text_width + pad_x
    bg_y1 = text_y + text_height + pad_y
    bg_layer = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg_layer)
    bg_draw.rectangle([bg_x0, bg_y0, bg_x1, bg_y1], fill=(0, 0, 0, 210))
    annotated = Image.alpha_composite(annotated, bg_layer)
    draw = ImageDraw.Draw(annotated)

    # Draw text in bright white — no need for outline, background handles contrast
    draw.text((text_x, text_y), label_text, font=font, fill=(255, 255, 255, 255))

    return annotated.convert("RGB")


def _draw_roi_rectangles(
    img: Image.Image,
    bboxes: List[Tuple[int, int, int, int]],
    colors: List[str],
    labels: List[str],
    border_frac: float = 0.015,
) -> Image.Image:
    """Return a copy of *img* with thick dark-bordered ROI rectangles."""
    annotated = img.copy().convert("RGBA")
    border_px = max(12, int(img.width * border_frac))

    for (left, top, right, bottom), color in zip(bboxes, colors):
        r, g, b, _ = [int(c * 255) for c in to_rgba(color)]
        rgba_color = (r, g, b, 255)
        rgba_dark = (20, 20, 20, 255)

        draw = ImageDraw.Draw(annotated)

        inner_width = max(2, border_px // 3)
        draw.rectangle(
            [left, top, right, bottom],
            outline=rgba_dark,
            width=border_px,
        )
        inset = inner_width // 2
        draw.rectangle(
            [left + inset, top + inset, right - inset, bottom - inset],
            outline=rgba_color,
            width=border_px - inner_width,
        )

    return annotated.convert("RGB")


# ============================================================================
# PLOT HELPERS
# ============================================================================
def _save_plot(
    images: List[Image.Image],
    save_path: str,
    dpi: int,
    titles: List[str],
    suffix_log: str = "",
) -> bool:
    """Plot images side-by-side and save with publication-quality formatting.

    Returns False if skipped (file already exists).
    """
    if os.path.isfile(save_path):
        logger.info(f"Skipping {suffix_log} — already exists: {save_path}")
        return False

    n = len(images)
    fig, axes = plt.subplots(1, n, figsize=(6.5 * n, 6.5), dpi=dpi)
    if n == 1:
        axes = [axes]

    for ax, img, title in zip(axes, images, titles):
        ax.imshow(img)
        ax.set_title(title, fontsize=12, pad=10, fontweight="bold", fontfamily="sans-serif")
        ax.axis("off")

    plt.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    logger.info(f"Saving {suffix_log} figure → {save_path}")
    plt.savefig(save_path, bbox_inches="tight", dpi=dpi, facecolor="white")
    plt.close()
    return True


def _save_annotated_full_view(
    images: List[Image.Image],
    bboxes_per_zoom: Dict[str, List[Tuple[int, int, int, int]]],
    roi_ids_per_zoom: Dict[str, List[str]],
    colors: List[str],
    save_path: str,
    dpi: int,
    titles: List[str],
    suffix_log: str = "",
) -> bool:
    """Save a full-view figure with all ROI rectangles from every zoom level.

    Returns False if the file already exists and was skipped.
    """
    if os.path.isfile(save_path):
        logger.info(f"Skipping {suffix_log} — already exists: {save_path}")
        return False

    all_bboxes: List[Tuple[int, int, int, int]] = []
    all_labels: List[str] = []
    all_colors: List[str] = []

    zoom_labels_ordered = list(bboxes_per_zoom.keys())
    zoom_colors = {
        zl: _ROI_COLORS[i % len(_ROI_COLORS)] for i, zl in enumerate(zoom_labels_ordered)
    }

    for zoom_label in zoom_labels_ordered:
        for bbox, roi_id in zip(bboxes_per_zoom[zoom_label], roi_ids_per_zoom[zoom_label]):
            all_bboxes.append(bbox)
            all_labels.append(f"{zoom_label}-{roi_id}")
            all_colors.append(zoom_colors[zoom_label])

    n = len(images)
    fig, axes = plt.subplots(1, n, figsize=(6.5 * n, 6.5), dpi=dpi)
    if n == 1:
        axes = [axes]

    for ax, img, title in zip(axes, images, titles):
        annotated = _draw_roi_rectangles(img, all_bboxes, all_colors, all_labels)
        ax.imshow(annotated)
        ax.set_title(title, fontsize=12, pad=10, fontweight="bold", fontfamily="sans-serif")
        ax.axis("off")

    legend_patches = [
        mpatches.Patch(color=zoom_colors[zl], label=f"{zl} ({len(roi_ids_per_zoom[zl])} ROIs)")
        for zl in zoom_labels_ordered
    ]
    fig.legend(
        handles=legend_patches,
        loc="lower center",
        ncol=min(len(zoom_labels_ordered), 4),
        fontsize=11,
        framealpha=0.98,
        title="Magnification level",
        title_fontsize=12,
        frameon=True,
        fancybox=False,
        edgecolor="black",
        facecolor="white",
    )

    plt.tight_layout(rect=[0, 0.08, 1, 1])
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    logger.info(f"Saving {suffix_log} figure → {save_path}")
    plt.savefig(save_path, bbox_inches="tight", dpi=dpi, facecolor="white")
    plt.close()
    return True


# ============================================================================
# MICRONS-PER-PIXEL LOOKUP
# ============================================================================

# Physical pixel sizes calibrated from the WSI pipeline output.
# Calibration: at 20× the crop is 1000 px and spans 100 µm → 0.10 µm/px.
# All other zoom levels are derived by doubling/halving that value per octave.
# Override via --mpp if your scanner differs.
_ZOOM_TO_MPP: Dict[str, float] = {
    "40x": 0.05,  # 0.05 µm / pixel  (512 px  ≈ 25.6 µm field)
    "20x": 0.10,  # 0.10 µm / pixel  (1000 px = 100 µm field)
    "10x": 0.20,  # 0.20 µm / pixel  (2000 px = 400 µm field)
    "5x": 0.40,  # 0.40 µm / pixel  (4000 px = 1600 µm field)
}

# Scale bar length (µm) chosen per zoom level so the bar is always a
# visually sensible fraction (~20-30%) of the field of view.
_ZOOM_TO_SCALE_BAR_MICRONS: Dict[str, int] = {
    "40x": 10,  # field ≈  25.6 µm  → 10 µm bar
    "20x": 20,  # field = 100   µm  → 20 µm bar
    "10x": 100,  # field = 400   µm  → 100 µm bar
    "5x": 500,  # field = 1600  µm  → 500 µm bar
}


# ============================================================================
# MAIN VISUALIZATION FUNCTION — PUBLICATION QUALITY
# ============================================================================
def visualize_side_by_side(
    he_path: str,
    gt_ihc_path: str,
    pred_ihc_path: str,
    save_path: str,
    dpi: int,
    title_he: str,
    title_gt: str,
    title_pred: str,
    regions: Optional[List[str]] = None,
    zoom_sizes: Optional[List[Tuple[str, int]]] = None,
    n_random_rois: int = 0,
    roi_seed: int = 42,
    add_scale_bars: bool = True,
    mpp: Optional[float] = None,
) -> None:
    """Load H&E, GT IHC, and Predicted IHC WSIs and save publication-quality
    comparison figures.

    Scale bar note
    --------------
    Scale bars are sized using the physical pixel size (microns-per-pixel, MPP)
    of the crop — not the output DPI.  For each zoom level the MPP is looked up
    from ``_ZOOM_TO_MPP`` (or overridden with ``mpp``).  This guarantees the bar
    always represents the correct tissue length.

    Args:
        regions           : named region keys from ``VALID_REGIONS``.
        zoom_sizes        : list of (label, pixel_size) pairs.
        n_random_rois     : number of random ROIs per zoom level (0 = disabled).
        roi_seed          : RNG seed for random ROI sampling.
        add_scale_bars    : whether to add scale bars (default True).
        mpp               : microns-per-pixel override (uses _ZOOM_TO_MPP if None).
    """
    if regions is None:
        regions = list(VALID_REGIONS)
    if zoom_sizes is None:
        zoom_sizes = [("40x", 512), ("20x", 1000), ("10x", 2000), ("5x", 4000)]

    invalid = [r for r in regions if r not in VALID_REGIONS]
    if invalid:
        raise ValueError(f"Unknown region(s): {invalid}. Valid: {list(VALID_REGIONS)}")

    for label, path in [
        ("H&E", he_path),
        ("GT IHC", gt_ihc_path),
        ("Predicted IHC", pred_ihc_path),
    ]:
        if not os.path.isfile(path):
            logger.error(f"{label} image not found: {path}")
            return

    logger.info(f"Loading images for publication-quality comparison (DPI: {dpi})...")
    logger.info(f"  H&E            : {he_path}")
    logger.info(f"  GT IHC         : {gt_ihc_path}")
    logger.info(f"  Predicted IHC  : {pred_ihc_path}")
    logger.info(f"  Regions        : {regions}")
    logger.info(f"  Zoom levels    : {[z[0] for z in zoom_sizes]}")
    logger.info(f"  Scale bars     : {add_scale_bars} (auto µm per zoom level)")
    if n_random_rois:
        logger.info(f"  Random ROIs    : {n_random_rois} per zoom (seed={roi_seed})")

    base_dir = os.path.dirname(os.path.abspath(save_path))
    base_name, ext = os.path.splitext(os.path.basename(save_path))
    if not ext:
        ext = ".png"

    named_outputs: List[Tuple[str, str, str, int]] = []
    for zoom_label, size in zoom_sizes:
        for region in regions:
            out_path = os.path.join(base_dir, f"{base_name}_{zoom_label}_{region}{ext}")
            named_outputs.append((out_path, zoom_label, region, size))

    full_view_done = os.path.isfile(save_path)
    pending_named = [(p, zl, r, s) for p, zl, r, s in named_outputs if not os.path.isfile(p)]
    n_already_named = len(named_outputs) - len(pending_named)

    sidecar_path = os.path.join(base_dir, f"{base_name}{_ROI_SIDECAR_SUFFIX}")
    annotated_path = os.path.join(base_dir, f"{base_name}_random_roi_annotated{ext}")

    random_mode = n_random_rois > 0
    if full_view_done and not pending_named:
        if not random_mode:
            logger.info(
                f"All outputs already exist "
                f"(1 full-view + {len(named_outputs)} crops) — nothing to do."
            )
            return

    if n_already_named:
        logger.info(
            f"Resuming: {n_already_named}/{len(named_outputs)} "
            f"region crop(s) already exist and will be skipped."
        )

    try:
        img_he = Image.open(he_path)
        img_gt = Image.open(gt_ihc_path)
        img_pred = Image.open(pred_ihc_path)
        w, h = img_he.size

        # ── 1. Plain full view ────────────────────────────────────────────────
        _save_plot(
            [img_he, img_gt, img_pred],
            save_path,
            dpi,
            [title_he, title_gt, title_pred],
            suffix_log="Full-view",
        )

        # ── 2. Named-region crops ─────────────────────────────────────────────
        total = len(named_outputs)
        done = n_already_named
        for out_path, zoom_label, region, size in named_outputs:
            if os.path.isfile(out_path):
                done += 1
                continue

            bbox = _region_bbox(w, h, size, region, img_he)
            crops = [img_he.crop(bbox), img_gt.crop(bbox), img_pred.crop(bbox)]

            if add_scale_bars:
                zoom_mpp = mpp if mpp is not None else _ZOOM_TO_MPP.get(zoom_label, 0.10)
                zoom_microns = _ZOOM_TO_SCALE_BAR_MICRONS.get(zoom_label, 50)
                crops = [_add_scale_bar(c, zoom_microns, zoom_mpp) for c in crops]

            region_label = _REGION_LABELS[region]
            _save_plot(
                crops,
                out_path,
                dpi,
                [
                    f"{title_he} ({zoom_label} — {region_label})",
                    f"{title_gt} ({zoom_label} — {region_label})",
                    f"{title_pred} ({zoom_label} — {region_label})",
                ],
                suffix_log=f"{zoom_label}-{region_label}",
            )
            for c in crops:
                c.close()
            done += 1
            logger.info(f"  Region progress: {done}/{total} done.")

        # ── 3. Random-ROI crops + annotated full view ─────────────────────────
        if random_mode:
            roi_data = _load_or_create_roi_sidecar(
                sidecar_path,
                img_he,
                w,
                h,
                zoom_sizes,
                n_random_rois,
                roi_seed,
            )

            roi_outputs: List[Tuple[str, str, str, Tuple[int, int, int, int]]] = []
            for zoom_label, size in zoom_sizes:
                for entry in roi_data["rois"][zoom_label]:
                    roi_id = entry["roi_id"]
                    bbox = tuple(entry["bbox"])
                    out_path = os.path.join(
                        base_dir,
                        f"{base_name}_random_{zoom_label}_{roi_id}{ext}",
                    )
                    roi_outputs.append((out_path, zoom_label, roi_id, bbox))

            pending_roi = [
                (p, zl, rid, bb) for p, zl, rid, bb in roi_outputs if not os.path.isfile(p)
            ]
            n_already_roi = len(roi_outputs) - len(pending_roi)
            annot_done = os.path.isfile(annotated_path)

            if annot_done and not pending_roi:
                logger.info(
                    f"All random-ROI outputs already exist "
                    f"({len(roi_outputs)} crops + annotated full-view) — skipping."
                )
            else:
                if n_already_roi:
                    logger.info(
                        f"Resuming random ROIs: {n_already_roi}/{len(roi_outputs)} "
                        f"crop(s) already exist and will be skipped."
                    )

                roi_total = len(roi_outputs)
                roi_done = n_already_roi
                for out_path, zoom_label, roi_id, bbox in roi_outputs:
                    if os.path.isfile(out_path):
                        roi_done += 1
                        continue

                    crops = [
                        img_he.crop(bbox),
                        img_gt.crop(bbox),
                        img_pred.crop(bbox),
                    ]

                    if add_scale_bars:
                        zoom_mpp = mpp if mpp is not None else _ZOOM_TO_MPP.get(zoom_label, 0.10)
                        zoom_microns = _ZOOM_TO_SCALE_BAR_MICRONS.get(zoom_label, 50)
                        crops = [_add_scale_bar(c, zoom_microns, zoom_mpp) for c in crops]

                    _save_plot(
                        crops,
                        out_path,
                        dpi,
                        [
                            f"{title_he} (Random {zoom_label} — {roi_id.upper()})",
                            f"{title_gt} (Random {zoom_label} — {roi_id.upper()})",
                            f"{title_pred} (Random {zoom_label} — {roi_id.upper()})",
                        ],
                        suffix_log=f"Random-{zoom_label}-{roi_id}",
                    )
                    for c in crops:
                        c.close()
                    roi_done += 1
                    logger.info(f"  Random-ROI progress: {roi_done}/{roi_total} done.")

                bboxes_per_zoom: Dict[str, List[Tuple]] = {}
                roi_ids_per_zoom: Dict[str, List[str]] = {}
                for zoom_label, _ in zoom_sizes:
                    bboxes_per_zoom[zoom_label] = [
                        tuple(e["bbox"]) for e in roi_data["rois"][zoom_label]
                    ]
                    roi_ids_per_zoom[zoom_label] = [
                        e["roi_id"] for e in roi_data["rois"][zoom_label]
                    ]

                _save_annotated_full_view(
                    images=[img_he, img_gt, img_pred],
                    bboxes_per_zoom=bboxes_per_zoom,
                    roi_ids_per_zoom=roi_ids_per_zoom,
                    colors=_ROI_COLORS,
                    save_path=annotated_path,
                    dpi=dpi,
                    titles=[title_he, title_gt, title_pred],
                    suffix_log="Annotated-full-view (random ROIs)",
                )

        img_he.close()
        img_gt.close()
        img_pred.close()

        logger.info("✓ All publication-quality visualizations saved successfully!")

    except Exception as e:
        logger.exception(f"Failed to generate visualization: {e}")


# ============================================================================
# ENTRY POINT
# ============================================================================
def main() -> None:
    """Entry point for ``python -m rocqipath.visualization.wsi_compare``.

    Parses command-line arguments describing a 3-panel comparison
    (H&E | ground-truth IHC | predicted IHC), either via a case manifest
    JSON (``--manifest``) or explicit per-image path overrides
    (``--he``/``--gt_ihc``/``--pred_ihc``), then generates and saves
    publication-quality comparison figures for the requested spatial
    regions and zoom levels.

    Returns
    -------
    None
        Side effects only: saved figure files and log output. Run with
        ``--help`` for the full, authoritative list of arguments (input
        paths, output naming, panel titles, DPI, ``--regions``,
        ``--zooms``, and any other options defined on the parser) — the
        parser's help text is generated dynamically via
        ``argparse.ArgumentDefaultsHelpFormatter``, so it always reflects
        the current defaults exactly.

    Notes
    -----
    Exactly one of ``--manifest`` or the three explicit
    ``--he``/``--gt_ihc``/``--pred_ihc`` paths must be provided — the
    manifest path takes all three image paths from a JSON file (as
    written elsewhere in the pipeline), while the explicit paths let the
    tool be used standalone against arbitrary files.
    """
    parser = argparse.ArgumentParser(
        description="Publication-Quality 3-Panel WSI Visualizer: H&E | GT IHC | Predicted IHC",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ── Manifest (primary input) ──────────────────────────────────────────────
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "Path to the case manifest JSON written by wsi_reconstruction.py. "
            "When provided, all image paths are read from the manifest."
        ),
    )

    # ── Per-image path overrides ──────────────────────────────────────────────
    parser.add_argument(
        "--he",
        default=None,
        dest="he_path",
        help="Path to the H&E TIFF. Required if --manifest is not provided.",
    )
    parser.add_argument(
        "--gt_ihc",
        default=None,
        dest="gt_ihc_path",
        help="Path to the GT IHC TIFF. Required if --manifest is not provided.",
    )
    parser.add_argument(
        "--pred_ihc",
        default=None,
        dest="pred_ihc_path",
        help="Path to the Predicted IHC TIFF. Required if --manifest is not provided.",
    )

    # ── Figure output ─────────────────────────────────────────────────────────
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Base path/filename for saved figures. "
            "Default when using --manifest: <wsi_dir>/<case_id>_wsi_comparison.png"
        ),
    )

    # ── Titles & DPI ─────────────────────────────────────────────────────────
    parser.add_argument("--title_he", default="H&E", help="Title for the H&E panel.")
    parser.add_argument(
        "--title_gt", default="Ground Truth IHC", help="Title for the GT IHC panel."
    )
    parser.add_argument(
        "--title_pred", default="Predicted IHC", help="Title for the Predicted IHC panel."
    )
    parser.add_argument(
        "--dpi", type=int, default=600, help="DPI for saved figures (300+ for print)."
    )

    # ── Named region selection ────────────────────────────────────────────────
    parser.add_argument(
        "--regions",
        nargs="+",
        default=list(VALID_REGIONS),
        choices=list(VALID_REGIONS),
        metavar="REGION",
        help=(
            "Which spatial regions to crop and save. "
            "One or more of: center, top_left, top_right, bottom_left, bottom_right. "
            "Defaults to all five. "
            "Example: --regions center top_left bottom_right"
        ),
    )

    # ── Zoom level selection ──────────────────────────────────────────────────
    parser.add_argument(
        "--zooms",
        nargs="+",
        default=["40x", "20x", "10x", "5x"],
        choices=["40x", "20x", "10x", "5x"],
        metavar="ZOOM",
        help=(
            "Which zoom levels (crop sizes) to generate. "
            "Choices: 40x (512 px), 20x (1000 px), 10x (2000 px), 5x (4000 px). "
            "Defaults to all four. "
            "Example: --zooms 40x 20x"
        ),
    )

    # ── Random ROI options ────────────────────────────────────────────────────
    parser.add_argument(
        "--random_rois",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Number of random ROIs to sample per zoom level (default: 0 = disabled). "
            "Example: --random_rois 3"
        ),
    )
    parser.add_argument(
        "--roi_seed",
        type=int,
        default=42,
        metavar="SEED",
        help="Random seed for ROI sampling (default: 42). Example: --roi_seed 7",
    )

    # ── Scale bar options ─────────────────────────────────────────────────────
    parser.add_argument(
        "--scale_bars",
        action="store_true",
        default=False,
        help="Add calibrated scale bars to crop figures (default: True).",
    )
    parser.add_argument(
        "--no_scale_bars",
        action="store_false",
        dest="scale_bars",
        help="Disable scale bars.",
    )
    parser.add_argument(
        "--mpp",
        type=float,
        default=None,
        metavar="MPP",
        help=(
            "Microns-per-pixel of the WSI at native (40x) resolution. "
            "Overrides the built-in zoom→MPP table (_ZOOM_TO_MPP). "
            "Typical value for a 40x scanner: 0.25. "
            "Defaults to NONE"
            "Example: --mpp 0.25"
        ),
    )

    args = parser.parse_args()

    # ── Validate random ROI count ─────────────────────────────────────────────
    if args.random_rois < 0:
        parser.error("--random_rois must be >= 0.")
    if args.random_rois > 10:
        parser.error("--random_rois must be <= 10.")

    # ── Resolve paths ─────────────────────────────────────────────────────────
    if args.manifest:
        manifest = _load_manifest(args.manifest)
        case_id = manifest["case_id"]
        wsi_dir = manifest["wsi_dir"]
        he_path = manifest["stains"]["gt_he"]
        gt_ihc_path = manifest["stains"]["gt_ihc"]
        pred_ihc_path = manifest["stains"]["prediction_ihc"]
        save_path = args.output or os.path.join(wsi_dir, f"{case_id}_wsi_comparison.png")
    else:
        missing = [
            n
            for n, v in [
                ("--he", args.he_path),
                ("--gt_ihc", args.gt_ihc_path),
                ("--pred_ihc", args.pred_ihc_path),
            ]
            if not v
        ]
        if missing:
            parser.error(
                f"When --manifest is not provided, these arguments are required: "
                f"{', '.join(missing)}"
            )
        he_path = args.he_path
        gt_ihc_path = args.gt_ihc_path
        pred_ihc_path = args.pred_ihc_path
        wsi_dir = os.path.dirname(os.path.abspath(he_path))
        save_path = args.output or os.path.join(wsi_dir, "wsi_comparison.png")

    # ── Build ordered zoom_sizes and regions lists ────────────────────────────
    _zoom_map = {"40x": 512, "20x": 1000, "10x": 2000, "5x": 4000}
    zoom_order = ["40x", "20x", "10x", "5x"]
    zoom_sizes = [(z, _zoom_map[z]) for z in zoom_order if z in args.zooms]
    regions = [r for r in VALID_REGIONS if r in args.regions]

    configure_logging(
        tool_name="RocqiPath — Publication-Quality Visualizer",
        subtitle="WSI Visualization Module",
        save_dir=wsi_dir,
    )

    logger.info("=" * 70)
    logger.info(f"{' VISUALIZATION CONFIGURATION':^70}")
    logger.info("=" * 70)
    logger.info(f"{'Regions':<25} : {regions}")
    logger.info(f"{'Zoom levels':<25} : {[z[0] for z in zoom_sizes]}")
    logger.info(f"{'Random ROIs':<25} : {args.random_rois}")
    logger.info(f"{'Scale bars':<25} : {args.scale_bars}")
    logger.info(f"{'MPP override':<25} : {args.mpp if args.mpp else 'auto'}")
    logger.info(f"{'Output base':<25} : {save_path}")
    logger.info(f"{'DPI':<25} : {args.dpi}")
    logger.info("=" * 70)

    visualize_side_by_side(
        he_path=he_path,
        gt_ihc_path=gt_ihc_path,
        pred_ihc_path=pred_ihc_path,
        save_path=save_path,
        dpi=args.dpi,
        title_he=args.title_he,
        title_gt=args.title_gt,
        title_pred=args.title_pred,
        regions=regions,
        zoom_sizes=zoom_sizes,
        n_random_rois=args.random_rois,
        roi_seed=args.roi_seed,
        add_scale_bars=args.scale_bars,
        mpp=args.mpp,
    )


if __name__ == "__main__":
    main()
