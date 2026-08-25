"""Alignment command for the unified RocqiPath CLI."""

from __future__ import annotations

import argparse


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add alignment arguments to a command parser."""
    parser.add_argument("input_dir", help="Directory containing WSI pair folders.")
    parser.add_argument("output_dir", help="Root directory for aligned outputs.")
    parser.add_argument("--method", choices=("valis", "orb"), default="valis")
    parser.add_argument("--pair-folders", nargs="*", default=[])
    parser.add_argument("--reference-name", default="reference")
    parser.add_argument("--moving-name", default="moving")
    parser.add_argument("--filename-pattern")
    parser.add_argument("--aligned-wsi-level", type=int, default=0)
    parser.add_argument("--patch-size", type=int, default=1024)
    parser.add_argument("--grid-density", type=int, default=1)
    parser.add_argument("--target-magnification", type=float, default=20.0)
    parser.add_argument("--reference-source-magnification", type=float)
    parser.add_argument("--moving-source-magnification", type=float)
    parser.add_argument("--valis-max-error-um", type=float)
    parser.add_argument("--qc", action="store_true", help="Save a center-patch QC figure.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Discover pairs without registration."
    )


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Run alignment from parsed command-line arguments."""
    from rocqipath.registration import AlignmentConfig, run_alignment

    config = AlignmentConfig(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        pair_folders=args.pair_folders,
        reference_name=args.reference_name,
        moving_name=args.moving_name,
        filename_pattern=args.filename_pattern,
        alignment_method=args.method,
        aligned_wsi_level=args.aligned_wsi_level,
        patch_size=args.patch_size,
        grid_density=args.grid_density,
        target_magnification=args.target_magnification,
        reference_source_magnification=args.reference_source_magnification,
        moving_source_magnification=args.moving_source_magnification,
        valis_max_error_um=args.valis_max_error_um,
        qc_enabled=args.qc,
        dry_run=args.dry_run,
    )
    results = run_alignment(config)
    print(f"Processed {len(results)} alignment result(s).")
    return 0
