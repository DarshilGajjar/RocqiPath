"""Tissue and TMA extraction commands for the unified CLI."""

from __future__ import annotations

import argparse


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add extraction arguments to a command parser."""
    parser.add_argument("input_dir", help="Directory containing input WSIs.")
    parser.add_argument("output_dir", help="Root directory for extracted regions.")
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


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Run WSI or TMA extraction from parsed arguments."""
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
