"""Reusable comparison-figure drawing and saving helpers."""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba
from PIL import Image, ImageDraw

from rocqipath.core.logging import logger
from rocqipath.visualization.roi import _ROI_COLORS


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


__all__ = [
    "_draw_roi_rectangles",
    "_save_plot",
    "_save_annotated_full_view",
]
