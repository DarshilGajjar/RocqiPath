"""
roqcipath.extraction.tissue_extraction
==================================
Whole-slide tissue region extraction pipeline.

For slides with multiple discrete tissue regions (e.g. microarrays or
biopsy punch collections), use roqcipath.extraction.core_extraction
instead. This module handles regular biopsies, resections, and any slide
containing a single contiguous tissue section.

The config is intentionally simple — no circularity filter,
no per-stain registration, no IHC enhancement.

Quickstart
----------
Batch (whole directory)::

    from roqcipath.extraction import TissueExtractionConfig, run_tissue_pipeline

    run_tissue_pipeline(
        input_dir  = "./data/wsi",
        output_dir = "./data/wsi/extracted",
        cfg        = TissueExtractionConfig(detection_level=2, min_area_fraction=0.005),
    )

Single slide::

    from roqcipath.extraction.tissue_extraction import TissueExtractionConfig, extract_tissue_regions

    regions = extract_tissue_regions("./slide_01.svs", "./out")
"""

from __future__ import annotations

__all__ = [
    "TissueExtractionConfig",
    "extract_tissue_regions",
    "run_tissue_pipeline",
]

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from roqcipath.extraction._extraction_engine import (
    SUPPORTED_EXTENSIONS,
    _BaseExtractionConfig,
    _detect_regions,
    _load_thumbnail,
    _region_outputs_exist,
    _resample_region,
    _resolve_vips_magnification,
    _save_preview,
    _save_tif,
    _write_region_manifest,
    _write_slide_manifest,
    configure_logging,
    logger,
)
from roqcipath.output import OutputLayout

try:
    import pyvips; _PYVIPS_AVAILABLE = True
except ImportError:
    pyvips = None; _PYVIPS_AVAILABLE = False  # type: ignore[assignment]

try:
    from roqcipath.logger import console, get_logger as _get_logger
    _log = _get_logger("tissue_extraction")
except Exception:
    import logging as _sl
    _log = _sl.getLogger("roqcipath.extraction.tissue_extraction")  # type: ignore[assignment]
    from rich.console import Console as _C
    console = _C(highlight=False)  # type: ignore[assignment]

from rich.panel import Panel
from rich.table import Table

# ── Intro banner — fires once when this module is first imported ──────────────
try:
    from roqcipath.logger import print_banner as _print_banner
    _print_banner()
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════════════
# TissueExtractionConfig
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TissueExtractionConfig(_BaseExtractionConfig):
    """Configuration for whole-slide tissue region extraction.

    All parameters are inherited from _BaseExtractionConfig.
    No multi-region-specific fields (circularity, per-stain detection,
    IHC enhancement) are present here — they are not applicable
    to regular whole-slide images.

    Parameters
    ----------
    detection_level : int
        Pyramid level for thumbnail loading (default 2, i.e. 1/4 resolution).
        Higher values are faster but less accurate for small tissue fragments.
    min_area_fraction : float
        Minimum region area as a fraction of the thumbnail area (default 0.005).
        Increase to filter small debris; decrease to capture small fragments.
    preview_scale : float
        Downscale factor for JPEG preview images (default 0.2).
    tif_tile, tif_pyramid, tif_compression, tif_quality
        Tiled pyramidal TIFF output options.
    skip_existing : bool
        Skip regions whose output files already exist (resume support).

    Examples
    --------
    Default — suitable for most whole-slide images::

        TissueExtractionConfig()

    Capture smaller fragments::

        TissueExtractionConfig(min_area_fraction=0.001)

    Faster compression for large datasets::

        TissueExtractionConfig(tif_compression="deflate", tif_quality=90)
    """
    # Override base defaults to suit whole-slide tissue
    detection_level:   Optional[int] = None  # deprecated pyramid-index override
    min_area_fraction: float = 0.005  # 0.5% — filters small debris


# ══════════════════════════════════════════════════════════════════════════════
# Rich config panel
# ══════════════════════════════════════════════════════════════════════════════

def _print_config_panel(cfg: TissueExtractionConfig,
                        input_dir: str, output_dir: str) -> None:
    """Render a Rich table summarising the resolved run configuration.

    Printed once at the start of :func:`run_tissue_pipeline` so the
    operator can see exactly which parameters will be used before
    processing begins.

    Parameters
    ----------
    cfg : TissueExtractionConfig
        The configuration whose fields are displayed.
    input_dir : str
        Input directory path, shown as the first row (not part of
        ``cfg`` since it's a pipeline argument rather than a config
        field).
    output_dir : str
        Output directory path, shown as the second row.

    Notes
    -----
    Purely a display/logging side effect — writes to
    :data:`roqcipath.logger.console` (or its local fallback) and returns
    nothing.
    """
    tbl = Table(show_header=False, box=None, padding=(0, 2))
    tbl.add_column("Key",   style="bold white", no_wrap=True)
    tbl.add_column("Value", style="bright_cyan")
    for k, v in [("Input dir", input_dir), ("Output dir", output_dir),
        ("Detection zoom",    f"{cfg.detection_magnification:g}x" if cfg.detection_level is None else f"legacy level {cfg.detection_level}"),
        ("Output zoom",       f"{cfg.target_magnification:g}x"),
        ("Min area fraction", f"{cfg.min_area_fraction:.4f}"),
        ("Preview scale",     f"{cfg.preview_scale:.2f}"),
        ("TIF compression",   cfg.tif_compression),
        ("TIF quality",       str(cfg.tif_quality)),
        ("Skip existing",     str(cfg.skip_existing))]:
        tbl.add_row(k, v)
    console.print(Panel(tbl, title="[bold green]Tissue Region Extraction[/]", expand=False))


# ══════════════════════════════════════════════════════════════════════════════
# Single-slide extraction
# ══════════════════════════════════════════════════════════════════════════════

def extract_tissue_regions(wsi_path: str, output_dir: str,
                           cfg: Optional[TissueExtractionConfig] = None,
                           ) -> List[Dict[str, Any]]:
    """Detect and extract all tissue regions from a single whole-slide image.

    Parameters
    ----------
    wsi_path : str
    output_dir : str
        A subdirectory named after the slide stem is created inside it.
    cfg : TissueExtractionConfig or None

    Returns
    -------
    list[dict]
        One dict per region with keys region_number, region_tag,
        relative_box, absolute_box, status.

    Raises
    ------
    FileNotFoundError  when wsi_path does not exist
    ImportError        when pyvips is not installed
    """
    if not _PYVIPS_AVAILABLE:
        raise ImportError("pyvips required. pip install roqcipath[extraction]")
    if not Path(wsi_path).is_file():
        raise FileNotFoundError(f"WSI not found: {wsi_path}")
    if cfg is None: cfg = TissueExtractionConfig()

    slide_name = Path(wsi_path).stem
    slide_dir = OutputLayout(output_dir).item_dir("tissue_extraction", slide_name)

    thumbnail = _load_thumbnail(
        Path(wsi_path),
        cfg.detection_level,
        target_magnification=cfg.detection_magnification,
        source_magnification=cfg.source_magnification,
    )
    rel_boxes = _detect_regions(thumbnail, cfg.min_area_fraction,
                                only_circles=False, min_circularity=0.0)

    if not rel_boxes:
        logger.warning(f"{slide_name} | No regions detected — "
                       f"try min_area_fraction < {cfg.min_area_fraction}")
        _write_slide_manifest(slide_dir / f"{slide_name}_manifest.json",
            pipeline="tissue", sample_id=slide_name,
            source_file=Path(wsi_path).name, n_regions=0, regions=[])
        return []

    logger.info(f"{slide_name} | {len(rel_boxes)} region(s) detected")

    full_img       = pyvips.Image.new_from_file(str(wsi_path), access="sequential")
    full_w, full_h = full_img.width, full_img.height
    full_dims      = {"width": full_w, "height": full_h}
    source_mag, mag_source = _resolve_vips_magnification(
        full_img, cfg.source_magnification
    )

    manifests: List[Dict[str, Any]] = []

    for idx, box in enumerate(rel_boxes):
        n   = idx + 1
        tag = f"region_{n:03d}"
        rdir = slide_dir

        x = int(box["rx"]*full_w); y = int(box["ry"]*full_h)
        w = int(box["rw"]*full_w); h = int(box["rh"]*full_h)
        x = max(0, min(x, full_w-1)); y = max(0, min(y, full_h-1))
        w = max(1, min(w, full_w-x)); h = max(1, min(h, full_h-y))
        abs_box: Dict[str, int] = {"x": x, "y": y, "w": w, "h": h}

        if cfg.skip_existing and _region_outputs_exist(rdir, tag):
            logger.info(f"  SKIPPED  {tag}"); status = "skipped_existing"
        else:
            region = _resample_region(
                full_img.crop(x, y, w, h),
                source_magnification=source_mag,
                target_magnification=cfg.target_magnification,
            )
            _save_tif(region, rdir / f"{tag}.tif", cfg)
            _save_preview(region, rdir / f"{tag}_preview.jpg", cfg.preview_scale)
            _write_region_manifest(rdir / f"{tag}_manifest.json",
                pipeline="tissue", sample_id=slide_name, region_number=n,
                source_file=Path(wsi_path).name, rel_box=box, abs_box=abs_box,
                full_slide_dims=full_dims, detection_source="otsu",
                extra_meta={
                    "source_magnification": source_mag,
                    "magnification_source": mag_source,
                    "output_magnification": cfg.target_magnification,
                })
            logger.success(f"  SAVED    {tag}"); status = "saved"

        manifests.append({"region_number": n, "region_tag": tag,
            "relative_box": box, "absolute_box": abs_box, "status": status})

    _write_slide_manifest(slide_dir / f"{slide_name}_manifest.json",
        pipeline="tissue", sample_id=slide_name,
        source_file=Path(wsi_path).name,
        n_regions=len(manifests),
        regions=manifests)
    return manifests


# ══════════════════════════════════════════════════════════════════════════════
# Batch entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_tissue_pipeline(input_dir: str, output_dir: str,
                        cfg: Optional[TissueExtractionConfig] = None,
                        ) -> Dict[str, List[Dict[str, Any]]]:
    """Detect and extract tissue regions from all WSI files in input_dir.

    Parameters
    ----------
    input_dir : str
    output_dir : str
    cfg : TissueExtractionConfig or None

    Returns
    -------
    dict  { slide_stem: [region_manifest, ...] }
    """
    if not _PYVIPS_AVAILABLE:
        raise ImportError("pyvips required. pip install roqcipath[extraction]")
    if cfg is None: cfg = TissueExtractionConfig()

    module_dir = OutputLayout(output_dir).module_dir("tissue_extraction")
    configure_logging(save_dir=str(module_dir), log_filename="tissue_extraction.log")
    _print_config_panel(cfg, input_dir, str(module_dir))

    wsi_files = sorted(p for p in Path(input_dir).iterdir()
                       if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not wsi_files:
        logger.warning(f"No WSI files found in {input_dir}"); return {}

    logger.info(f"Tissue pipeline — {len(wsi_files)} slide(s)")
    results: Dict[str, List[Dict[str, Any]]] = {}

    for wsi_path in wsi_files:
        logger.info(f"Processing: {wsi_path.name}")
        try:
            regions = extract_tissue_regions(str(wsi_path), output_dir, cfg)
            results[wsi_path.stem] = regions
            logger.success(f"{wsi_path.name} — {len(regions)} region(s)")
        except Exception as exc:
            logger.exception(f"{wsi_path.name} failed: {exc}")

    logger.success(f"Tissue pipeline complete — {len(results)}/{len(wsi_files)} processed")
    return results
