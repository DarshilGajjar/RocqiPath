"""Stateless contour, resize, coordinate, annotation, and crop geometry."""

from __future__ import annotations

from typing import Any, Callable

from rocqipath.core.logging import logger
from rocqipath.core.tissue import pil_brightness_saturation_fraction

EDGE_MARGIN = 0.05
REGION_TISSUE_THRESHOLD = 0.50
REGION_SEARCH_RADIUS_FRAC = 0.25
REGION_SEARCH_STEP_FRAC = 0.02
REGION_THUMB_SIZE = 64
TISSUE_BRIGHTNESS_THRESHOLD = 220
TISSUE_SATURATION_THRESHOLD = 0.05


def resize_twostep(image: Any, out_size: int) -> Any:
    """Downsample with BOX followed by LANCZOS to minimize aliasing."""
    from PIL import Image

    if image.size == (out_size, out_size):
        return image
    width, height = image.size
    if width > 2 * out_size and height > 2 * out_size:
        image = image.resize((2 * out_size, 2 * out_size), Image.Resampling.BOX)
    return image.resize((out_size, out_size), Image.Resampling.LANCZOS)


def sort_contours_spatially(contours: list[Any]) -> list[Any]:
    """Sort OpenCV contours top-to-bottom and left-to-right within rows."""
    import cv2

    if not contours:
        return []
    boxes = [cv2.boundingRect(contour) for contour in contours]
    centroids = [(x + width // 2, y + height // 2) for x, y, width, height in boxes]
    average_height = sum(box[3] for box in boxes) / len(boxes)
    row_tolerance = average_height * 0.5
    items = sorted(zip(contours, centroids, boxes), key=lambda item: item[1][1])
    rows: list[list[Any]] = []
    current_row = [items[0]]
    for item in items[1:]:
        if abs(item[1][1] - current_row[-1][1][1]) < row_tolerance:
            current_row.append(item)
        else:
            rows.append(current_row)
            current_row = [item]
    if current_row:
        rows.append(current_row)
    result: list[Any] = []
    for row in rows:
        row.sort(key=lambda item: item[1][0])
        result.extend(item[0] for item in row)
    return result


def transform_coords(registrar: Any, x: int, y: int) -> tuple[int | None, int | None]:
    """Map a base-level reference coordinate into the target slide."""
    import cv2
    import numpy as np

    if registrar.method == "valis" and registrar._slide_ref_valis is not None:
        try:
            coordinates = np.array([[x, y]], dtype=float)
            warped = registrar._slide_ref_valis.warp_xy_from_to(
                coordinates,
                registrar._slide_tgt_valis,
            )
            return int(warped[0, 0]), int(warped[0, 1])
        except Exception as exc:
            logger.warning(f"[WARN] warp_xy_from_to failed at ({x},{y}): {exc}")
            return None, None
    if registrar.method == "orb" and registrar.orb_matrix is not None:
        scales = (
            registrar.orb_ref_scale_x,
            registrar.orb_ref_scale_y,
            registrar.orb_tgt_scale_x,
            registrar.orb_tgt_scale_y,
        )
        if any(value is None or value <= 0 for value in scales):
            return None, None
        point = np.array(
            [[[x / registrar.orb_ref_scale_x, y / registrar.orb_ref_scale_y]]],
            dtype=np.float32,
        )
        transformed = cv2.perspectiveTransform(point, registrar.orb_matrix)
        return (
            int(transformed[0, 0, 0] * registrar.orb_tgt_scale_x),
            int(transformed[0, 0, 1] * registrar.orb_tgt_scale_y),
        )
    return None, None


def tissue_fraction(image: Any, bbox: tuple[int, int, int, int]) -> float:
    """Return the comparison workflow's brightness-and-saturation tissue fraction."""
    return pil_brightness_saturation_fraction(
        image,
        bbox,
        thumbnail_size=REGION_THUMB_SIZE,
        brightness_threshold=TISSUE_BRIGHTNESS_THRESHOLD,
        saturation_threshold=TISSUE_SATURATION_THRESHOLD,
    )


def region_bbox(
    width: int,
    height: int,
    size: int,
    region: str,
    image: Any | None = None,
    *,
    tissue_fraction_fn: Callable[[Any, tuple[int, int, int, int]], float] = tissue_fraction,
    tissue_threshold: float = REGION_TISSUE_THRESHOLD,
    edge_margin: float = EDGE_MARGIN,
    search_radius_fraction: float = REGION_SEARCH_RADIUS_FRAC,
    search_step_fraction: float = REGION_SEARCH_STEP_FRAC,
) -> tuple[int, int, int, int]:
    """Return the first qualifying tissue crop near a named image anchor."""

    def clamp(left: int, top: int) -> tuple[int, int, int, int]:
        right = min(width, left + size)
        bottom = min(height, top + size)
        left = max(0, right - size)
        top = max(0, bottom - size)
        return left, top, right, bottom

    margin_x = int(width * edge_margin)
    margin_y = int(height * edge_margin)
    half = size // 2
    anchors = {
        "center": (width // 2, height // 2),
        "top_left": (margin_x + half, margin_y + half),
        "top_right": (width - margin_x - half, margin_y + half),
        "bottom_left": (margin_x + half, height - margin_y - half),
        "bottom_right": (width - margin_x - half, height - margin_y - half),
    }
    if region not in anchors:
        raise ValueError(f"Unknown region '{region}'. Valid choices: {list(anchors)}")
    center_x, center_y = anchors[region]
    nominal = clamp(center_x - half, center_y - half)
    if image is None:
        return nominal
    direction_map = {
        "center": [
            (+1, 0),
            (-1, 0),
            (0, +1),
            (0, -1),
            (+1, +1),
            (-1, +1),
            (+1, -1),
            (-1, -1),
        ],
        "top_left": [(+1, +1)],
        "top_right": [(-1, +1)],
        "bottom_left": [(+1, -1)],
        "bottom_right": [(-1, -1)],
    }
    step_x = max(1, int(width * search_step_fraction))
    step_y = max(1, int(height * search_step_fraction))
    max_dx = int(width * search_radius_fraction)
    max_dy = int(height * search_radius_fraction)
    seen: set[tuple[int, int, int, int]] = set()
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    for dx_sign, dy_sign in direction_map[region]:
        dx = 0
        while dx <= max_dx:
            dy = 0
            while dy <= max_dy:
                candidate_x = center_x + dx_sign * dx
                candidate_y = center_y + dy_sign * dy
                bbox = clamp(candidate_x - half, candidate_y - half)
                if bbox not in seen:
                    seen.add(bbox)
                    candidates.append(((dx**2 + dy**2) ** 0.5, bbox))
                dy += step_y
            dx += step_x
    candidates.sort(key=lambda item: item[0])
    best_fraction = -1.0
    best_bbox = nominal
    for _distance, bbox in candidates:
        fraction = tissue_fraction_fn(image, bbox)
        if fraction > best_fraction:
            best_fraction = fraction
            best_bbox = bbox
        if fraction >= tissue_threshold:
            logger.debug(f"[{region}] accepted at tissue={fraction:.1%}  bbox={bbox}")
            return bbox
    logger.warning(
        f"[{region}] No crop reached {tissue_threshold:.0%} tissue "
        f"({len(candidates)} positions searched, best={best_fraction:.1%}). "
        f"Using best available. Lower REGION_TISSUE_THRESHOLD or raise "
        f"REGION_SEARCH_RADIUS_FRAC if this happens frequently."
    )
    return best_bbox


def add_scale_bar(
    image: Any,
    microns: int,
    microns_per_pixel: float,
    location: str = "bottom_left",
    thickness: int | None = None,
) -> Any:
    """Add the comparison workflow's calibrated scale bar to a PIL image."""
    from PIL import Image, ImageDraw, ImageFont

    if thickness is None:
        thickness = max(2, int(image.width * 0.006))
    bar_length_px = int(microns / microns_per_pixel)
    bar_length_px = min(bar_length_px, int(image.width * 0.40))
    bar_length_px = max(bar_length_px, 20)
    font_size = max(28, int(image.width * 0.055))
    margin = max(15, int(image.width * 0.03))
    tick_height = thickness * 3
    vertical_space = tick_height + font_size + 30
    locations = {
        "bottom_left": lambda width, height: (
            margin,
            height - margin - vertical_space,
        ),
        "bottom_right": lambda width, height: (
            width - margin - bar_length_px,
            height - margin - vertical_space,
        ),
        "top_left": lambda _width, _height: (margin, margin),
        "top_right": lambda width, _height: (
            width - margin - bar_length_px,
            margin,
        ),
    }
    if location not in locations:
        location = "bottom_left"
    x, y = locations[location](image.width, image.height)
    x = max(0, min(x, image.width - bar_length_px))
    y = max(0, min(y, image.height - vertical_space))
    annotated = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(annotated)
    draw.line(
        [(x, y), (x + bar_length_px, y)],
        fill=(255, 255, 255, 255),
        width=thickness,
    )
    draw.line(
        [(x, y - tick_height // 2), (x, y + tick_height // 2)],
        fill=(255, 255, 255, 255),
        width=thickness,
    )
    draw.line(
        [
            (x + bar_length_px, y - tick_height // 2),
            (x + bar_length_px, y + tick_height // 2),
        ],
        fill=(255, 255, 255, 255),
        width=thickness,
    )
    label_text = f"{microns} µm"
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            font_size,
        )
    except (OSError, IOError):
        font = ImageFont.load_default()
    text_bbox = draw.textbbox((0, 0), label_text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = x + (bar_length_px - text_width) // 2
    text_y = y + tick_height + 8
    padding_x = max(6, font_size // 5)
    padding_y = max(4, font_size // 8)
    background = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
    background_draw = ImageDraw.Draw(background)
    background_draw.rectangle(
        [
            text_x - padding_x,
            text_y - padding_y,
            text_x + text_width + padding_x,
            text_y + text_height + padding_y,
        ],
        fill=(0, 0, 0, 210),
    )
    annotated = Image.alpha_composite(annotated, background)
    draw = ImageDraw.Draw(annotated)
    draw.text(
        (text_x, text_y),
        label_text,
        font=font,
        fill=(255, 255, 255, 255),
    )
    return annotated.convert("RGB")


__all__ = [
    "add_scale_bar",
    "region_bbox",
    "resize_twostep",
    "sort_contours_spatially",
    "tissue_fraction",
    "transform_coords",
]
