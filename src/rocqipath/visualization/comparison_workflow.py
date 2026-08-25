"""Crop planning and figure-generation stages for WSI comparisons."""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from PIL import Image

from rocqipath.core.logging import logger

from rocqipath.utils.geometry import (
    add_scale_bar as _add_scale_bar_impl,
    region_bbox as _region_bbox_impl,
    tissue_fraction as _tissue_fraction_impl,
)
from rocqipath.visualization.figure_helpers import (
    _save_annotated_full_view,
    _save_plot,
)
from rocqipath.visualization.roi import (
    _ROI_COLORS,
    _ROI_SIDECAR_SUFFIX,
    _load_or_create_roi_sidecar,
)

VALID_REGIONS: Tuple[str, ...] = (
    "center",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
)
_REGION_LABELS = {
    "center": "Center",
    "top_left": "Top-Left",
    "top_right": "Top-Right",
    "bottom_left": "Bottom-Left",
    "bottom_right": "Bottom-Right",
}
_ZOOM_TO_MPP = {"40x": 0.05, "20x": 0.10, "10x": 0.20, "5x": 0.40}
_ZOOM_TO_SCALE_BAR_MICRONS = {"40x": 10, "20x": 20, "10x": 100, "5x": 500}
_EDGE_MARGIN = 0.05
REGION_TISSUE_THRESHOLD = 0.50
REGION_SEARCH_RADIUS_FRAC = 0.25
REGION_SEARCH_STEP_FRAC = 0.02


def _tissue_fraction(image: Image.Image, bbox: Tuple[int, int, int, int]) -> float:
    """Delegate the historical comparison tissue-coverage calculation."""
    return _tissue_fraction_impl(image, bbox)


def _region_bbox(
    width: int,
    height: int,
    size: int,
    region: str,
    image: Optional[Image.Image] = None,
) -> Tuple[int, int, int, int]:
    """Resolve a named crop using the historical tissue-search settings."""
    return _region_bbox_impl(
        width,
        height,
        size,
        region,
        image,
        tissue_fraction_fn=_tissue_fraction,
        tissue_threshold=REGION_TISSUE_THRESHOLD,
        edge_margin=_EDGE_MARGIN,
        search_radius_fraction=REGION_SEARCH_RADIUS_FRAC,
        search_step_fraction=REGION_SEARCH_STEP_FRAC,
    )


def _add_scale_bar(
    image: Image.Image,
    microns: int,
    microns_per_pixel: float,
    location: str = "bottom_left",
    thickness: int = None,
) -> Image.Image:
    """Draw a calibrated bar while preserving the former helper signature."""
    return _add_scale_bar_impl(image, microns, microns_per_pixel, location, thickness)


def _named_output_plan(
    base_dir: str,
    base_name: str,
    extension: str,
    zoom_sizes: List[Tuple[str, int]],
    regions: List[str],
) -> List[Tuple[str, str, str, int]]:
    """Build deterministic paths for every named-region crop."""
    return [
        (
            os.path.join(base_dir, f"{base_name}_{zoom_label}_{region}{extension}"),
            zoom_label,
            region,
            size,
        )
        for zoom_label, size in zoom_sizes
        for region in regions
    ]


def _scale_crops(
    crops: List[Image.Image],
    zoom_label: str,
    add_scale_bars: bool,
    mpp: Optional[float],
) -> List[Image.Image]:
    """Apply the established zoom calibration to a list of crops."""
    if not add_scale_bars:
        return crops
    zoom_mpp = mpp if mpp is not None else _ZOOM_TO_MPP.get(zoom_label, 0.10)
    zoom_microns = _ZOOM_TO_SCALE_BAR_MICRONS.get(zoom_label, 50)
    return [_add_scale_bar(crop, zoom_microns, zoom_mpp) for crop in crops]


def _save_named_crops(
    images: List[Image.Image],
    outputs: List[Tuple[str, str, str, int]],
    *,
    already_saved: int,
    dpi: int,
    titles: List[str],
    add_scale_bars: bool,
    mpp: Optional[float],
) -> None:
    """Save all missing named-region crops in their original order."""
    width, height = images[0].size
    done = already_saved
    for out_path, zoom_label, region, size in outputs:
        if os.path.isfile(out_path):
            done += 1
            continue
        bbox = _region_bbox(width, height, size, region, images[0])
        crops = _scale_crops(
            [image.crop(bbox) for image in images],
            zoom_label,
            add_scale_bars,
            mpp,
        )
        region_label = _REGION_LABELS[region]
        _save_plot(
            crops,
            out_path,
            dpi,
            [f"{title} ({zoom_label} — {region_label})" for title in titles],
            suffix_log=f"{zoom_label}-{region_label}",
        )
        for crop in crops:
            crop.close()
        done += 1
        logger.info(f"  Region progress: {done}/{len(outputs)} done.")


def _random_output_plan(
    base_dir: str,
    base_name: str,
    extension: str,
    zoom_sizes: List[Tuple[str, int]],
    roi_data: Dict,
) -> List[Tuple[str, str, str, Tuple[int, int, int, int]]]:
    """Build paths and bounding boxes for persisted random ROIs."""
    outputs = []
    for zoom_label, _size in zoom_sizes:
        for entry in roi_data["rois"][zoom_label]:
            roi_id = entry["roi_id"]
            outputs.append(
                (
                    os.path.join(
                        base_dir,
                        f"{base_name}_random_{zoom_label}_{roi_id}{extension}",
                    ),
                    zoom_label,
                    roi_id,
                    tuple(entry["bbox"]),
                )
            )
    return outputs


def _save_random_crops(
    images: List[Image.Image],
    outputs: List[Tuple[str, str, str, Tuple[int, int, int, int]]],
    *,
    dpi: int,
    titles: List[str],
    add_scale_bars: bool,
    mpp: Optional[float],
) -> None:
    """Save missing random-ROI crops and retain historical resume logging."""
    already_saved = sum(os.path.isfile(path) for path, *_rest in outputs)
    if already_saved:
        logger.info(
            f"Resuming random ROIs: {already_saved}/{len(outputs)} "
            f"crop(s) already exist and will be skipped."
        )
    done = already_saved
    for out_path, zoom_label, roi_id, bbox in outputs:
        if os.path.isfile(out_path):
            done += 1
            continue
        crops = _scale_crops(
            [image.crop(bbox) for image in images],
            zoom_label,
            add_scale_bars,
            mpp,
        )
        _save_plot(
            crops,
            out_path,
            dpi,
            [f"{title} (Random {zoom_label} — {roi_id.upper()})" for title in titles],
            suffix_log=f"Random-{zoom_label}-{roi_id}",
        )
        for crop in crops:
            crop.close()
        done += 1
        logger.info(f"  Random-ROI progress: {done}/{len(outputs)} done.")


def _save_roi_annotation(
    images: List[Image.Image],
    roi_data: Dict,
    zoom_sizes: List[Tuple[str, int]],
    annotated_path: str,
    dpi: int,
    titles: List[str],
) -> None:
    """Save the full-view ROI rectangle annotation."""
    bboxes_per_zoom = {
        zoom_label: [tuple(entry["bbox"]) for entry in roi_data["rois"][zoom_label]]
        for zoom_label, _size in zoom_sizes
    }
    roi_ids_per_zoom = {
        zoom_label: [entry["roi_id"] for entry in roi_data["rois"][zoom_label]]
        for zoom_label, _size in zoom_sizes
    }
    _save_annotated_full_view(
        images=images,
        bboxes_per_zoom=bboxes_per_zoom,
        roi_ids_per_zoom=roi_ids_per_zoom,
        colors=_ROI_COLORS,
        save_path=annotated_path,
        dpi=dpi,
        titles=titles,
        suffix_log="Annotated-full-view (random ROIs)",
    )


def _save_random_outputs(
    images: List[Image.Image],
    *,
    sidecar_path: str,
    annotated_path: str,
    base_dir: str,
    base_name: str,
    extension: str,
    zoom_sizes: List[Tuple[str, int]],
    n_random_rois: int,
    roi_seed: int,
    dpi: int,
    titles: List[str],
    add_scale_bars: bool,
    mpp: Optional[float],
) -> None:
    """Load or sample ROI coordinates, then save crops and annotation."""
    width, height = images[0].size
    roi_data = _load_or_create_roi_sidecar(
        sidecar_path,
        images[0],
        width,
        height,
        zoom_sizes,
        n_random_rois,
        roi_seed,
    )
    outputs = _random_output_plan(base_dir, base_name, extension, zoom_sizes, roi_data)
    pending = [entry for entry in outputs if not os.path.isfile(entry[0])]
    if os.path.isfile(annotated_path) and not pending:
        logger.info(
            f"All random-ROI outputs already exist "
            f"({len(outputs)} crops + annotated full-view) — skipping."
        )
        return
    _save_random_crops(
        images,
        outputs,
        dpi=dpi,
        titles=titles,
        add_scale_bars=add_scale_bars,
        mpp=mpp,
    )
    _save_roi_annotation(images, roi_data, zoom_sizes, annotated_path, dpi, titles)


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
    """Generate full-view, named-region, and random-ROI comparisons.

    Parameters
    ----------
    he_path : str
        H&E WSI path.
    gt_ihc_path : str
        Ground-truth IHC WSI path.
    pred_ihc_path : str
        Predicted IHC WSI path.
    save_path : str
        Base path for the full-view figure; crop names derive from its stem.
    dpi : int
        Figure resolution in dots per inch. This affects output rendering,
        not physical scale-bar calibration.
    title_he, title_gt, title_pred : str
        Panel titles.
    regions : list of str, optional
        Named anchors from :data:`VALID_REGIONS`. Defaults to all anchors.
    zoom_sizes : list of tuple of (str, int), optional
        Zoom label and square crop edge in source-image pixels.
    n_random_rois : int, optional
        Random tissue ROIs per zoom. Zero disables random selection.
    roi_seed : int, optional
        Seed persisted with the random-ROI sidecar.
    add_scale_bars : bool, optional
        Add physically calibrated bars to crop panels.
    mpp : float, optional
        Micrometres per crop pixel. When omitted, the historical zoom
        lookup table supplies calibration.

    Returns
    -------
    None
        Figures and the optional ROI sidecar are written as side effects.

    Raises
    ------
    ValueError
        If ``regions`` contains an unknown anchor.

    Notes
    -----
    Existing outputs are skipped to support resume. Named-region search
    scores tissue on the H&E image; identical bounding boxes are then
    applied to all three panels.

    Examples
    --------
    Use :command:`rocqipath compare --help` for a complete file-backed
    example without loading scanner data during documentation tests.
    """
    regions = list(VALID_REGIONS) if regions is None else regions
    zoom_sizes = (
        [("40x", 512), ("20x", 1000), ("10x", 2000), ("5x", 4000)]
        if zoom_sizes is None
        else zoom_sizes
    )
    invalid = [region for region in regions if region not in VALID_REGIONS]
    if invalid:
        raise ValueError(f"Unknown region(s): {invalid}. Valid: {list(VALID_REGIONS)}")
    for label, path in (
        ("H&E", he_path),
        ("GT IHC", gt_ihc_path),
        ("Predicted IHC", pred_ihc_path),
    ):
        if not os.path.isfile(path):
            logger.error(f"{label} image not found: {path}")
            return

    logger.info(f"Loading images for publication-quality comparison (DPI: {dpi})...")
    logger.info(f"  H&E            : {he_path}")
    logger.info(f"  GT IHC         : {gt_ihc_path}")
    logger.info(f"  Predicted IHC  : {pred_ihc_path}")
    logger.info(f"  Regions        : {regions}")
    logger.info(f"  Zoom levels    : {[zoom[0] for zoom in zoom_sizes]}")
    logger.info(f"  Scale bars     : {add_scale_bars} (auto µm per zoom level)")
    if n_random_rois:
        logger.info(f"  Random ROIs    : {n_random_rois} per zoom (seed={roi_seed})")

    base_dir = os.path.dirname(os.path.abspath(save_path))
    base_name, extension = os.path.splitext(os.path.basename(save_path))
    extension = extension or ".png"
    outputs = _named_output_plan(base_dir, base_name, extension, zoom_sizes, regions)
    pending = [entry for entry in outputs if not os.path.isfile(entry[0])]
    already_saved = len(outputs) - len(pending)
    random_mode = n_random_rois > 0
    if os.path.isfile(save_path) and not pending and not random_mode:
        logger.info(
            f"All outputs already exist (1 full-view + {len(outputs)} crops) — nothing to do."
        )
        return
    if already_saved:
        logger.info(
            f"Resuming: {already_saved}/{len(outputs)} "
            f"region crop(s) already exist and will be skipped."
        )

    try:
        images = [Image.open(he_path), Image.open(gt_ihc_path), Image.open(pred_ihc_path)]
        titles = [title_he, title_gt, title_pred]
        _save_plot(images, save_path, dpi, titles, suffix_log="Full-view")
        _save_named_crops(
            images,
            outputs,
            already_saved=already_saved,
            dpi=dpi,
            titles=titles,
            add_scale_bars=add_scale_bars,
            mpp=mpp,
        )
        if random_mode:
            _save_random_outputs(
                images,
                sidecar_path=os.path.join(base_dir, f"{base_name}{_ROI_SIDECAR_SUFFIX}"),
                annotated_path=os.path.join(
                    base_dir,
                    f"{base_name}_random_roi_annotated{extension}",
                ),
                base_dir=base_dir,
                base_name=base_name,
                extension=extension,
                zoom_sizes=zoom_sizes,
                n_random_rois=n_random_rois,
                roi_seed=roi_seed,
                dpi=dpi,
                titles=titles,
                add_scale_bars=add_scale_bars,
                mpp=mpp,
            )
        for image in images:
            image.close()
        logger.info("✓ All publication-quality visualizations saved successfully!")
    except Exception as exc:
        logger.exception(f"Failed to generate visualization: {exc}")
