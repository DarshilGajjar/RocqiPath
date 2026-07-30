"""Tissue and TMA extraction commands for the unified CLI."""

from __future__ import annotations

import argparse

from rocqipath.cli.prompts import (
    _get_bool,
    _get_dir,
    _get_existing_dir,
    _get_float,
    _get_optional_float,
    _get_stain_list,
)
from rocqipath.core.logging import logger


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add extraction arguments to a command parser."""
    parser.add_argument("input_dir", nargs="?", help="Directory containing input WSIs.")
    parser.add_argument("output_dir", nargs="?", help="Root directory for extracted regions.")
    parser.add_argument("--mode", choices=("wsi", "tma"), default="wsi")
    parser.add_argument("--target-magnification", type=float, default=20.0)
    parser.add_argument("--detection-magnification", type=float, default=1.25)
    parser.add_argument("--source-magnification", type=float)
    parser.add_argument("--min-area-fraction", type=float)
    parser.add_argument("--target-stains", nargs="+", default=["all"])
    parser.add_argument("--min-circularity", type=float, default=0.70)
    parser.add_argument("--all-shapes", action="store_true", help="Disable circularity filtering.")
    parser.add_argument("--box-scale", type=float, default=1.0)
    parser.add_argument("--shared-detection", action="store_true")
    parser.add_argument("--no-fallback-to-reference", action="store_true")
    parser.add_argument("--no-ihc-enhance", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Do not skip complete outputs.")
    parser.add_argument("--interactive", action="store_true")


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Run WSI or TMA extraction from parsed arguments."""
    if args.interactive:
        return run_tma_interactive() if args.mode == "tma" else run_wsi_interactive()
    if not args.input_dir or not args.output_dir:
        parser.error("input_dir and output_dir are required unless --interactive is used")

    if args.mode == "wsi":
        from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

        config = TissueExtractionConfig(
            target_magnification=args.target_magnification,
            detection_magnification=args.detection_magnification,
            source_magnification=args.source_magnification,
            min_area_fraction=(0.005 if args.min_area_fraction is None else args.min_area_fraction),
            skip_existing=not args.overwrite,
        )
        run_tissue_pipeline(args.input_dir, args.output_dir, config)
        return 0

    from rocqipath.extraction import TMAExtractionConfig, run_tma_extraction_pipeline

    config = TMAExtractionConfig(
        target_magnification=args.target_magnification,
        detection_magnification=args.detection_magnification,
        source_magnification=args.source_magnification,
        min_area_fraction=(0.0005 if args.min_area_fraction is None else args.min_area_fraction),
        min_circularity=args.min_circularity,
        only_circles=not args.all_shapes,
        box_scale=args.box_scale,
        per_stain_detection=not args.shared_detection,
        fallback_to_he=not args.no_fallback_to_reference,
        ihc_enhance=not args.no_ihc_enhance,
        skip_existing=not args.overwrite,
    )
    run_tma_extraction_pipeline(
        input_dir=args.input_dir,
        output_root=args.output_dir,
        cfg=config,
        target_stains=args.target_stains,
    )
    return 0


def run_wsi_interactive() -> int:
    """Collect and run ordinary whole-slide tissue extraction settings."""
    from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

    print("\n" + "─" * 72)
    print("  Tissue Extraction — WSI mode")
    print("─" * 72)
    input_dir = _get_existing_dir("  Input directory: ")
    output_dir = _get_dir("  General output root: ")
    config = TissueExtractionConfig(
        target_magnification=_get_float("Output magnification (physical x)", 20.0),
        detection_magnification=_get_float("Detection magnification (physical x)", 1.25),
        source_magnification=_get_optional_float(
            "Source objective x if slide metadata is missing (Enter = metadata)"
        ),
        min_area_fraction=_get_float("Min area fraction", 0.005),
        skip_existing=_get_bool("Skip complete existing regions?", True),
    )
    run_tissue_pipeline(input_dir, output_dir, config)
    return 0


def run_tma_interactive() -> int:
    """Collect and run TMA/core extraction settings."""
    from rocqipath.extraction import TMAExtractionConfig, run_tma_extraction_pipeline

    print("\n" + "─" * 72)
    print("  Tissue Extraction — TMA/core mode")
    print("─" * 72)
    input_dir = _get_existing_dir("  Input directory: ")
    output_dir = _get_dir("  Output directory: ")
    target_stains = _get_stain_list("Target stains/biomarkers")
    config = TMAExtractionConfig(
        target_magnification=_get_float("Output magnification (physical x)", 20.0),
        detection_magnification=_get_float("Detection magnification (physical x)", 1.25),
        source_magnification=_get_optional_float(
            "Source objective x if metadata is missing (Enter = metadata)"
        ),
        min_area_fraction=_get_float("Min area fraction", 0.0005),
        min_circularity=_get_float("Min circularity [0-1]", 0.70),
        only_circles=_get_bool("Circles only?", True),
        box_scale=_get_float("Box scale (1.0 = exact fit)", 1.0),
        per_stain_detection=_get_bool("Per-stain Otsu detection?", True),
        fallback_to_he=_get_bool("Fallback to H&E on count mismatch?", True),
        ihc_enhance=_get_bool("Apply IHC CLAHE enhancement?", True),
        skip_existing=_get_bool("Skip already-processed cores?", True),
    )
    try:
        run_tma_extraction_pipeline(
            input_dir=input_dir,
            output_root=output_dir,
            cfg=config,
            target_stains=target_stains,
        )
        return 0
    except Exception as exc:
        logger.exception(f"Extraction pipeline failed: {exc}")
        return 1
