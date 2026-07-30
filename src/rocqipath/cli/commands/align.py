"""Alignment command for the unified RocqiPath CLI."""

from __future__ import annotations

import argparse

from rocqipath.cli.prompts import (
    _get_bool,
    _get_dir,
    _get_existing_dir,
    _get_float,
    _get_int,
    _get_optional_float,
)
from rocqipath.core.logging import logger


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add alignment arguments to a command parser."""
    parser.add_argument("input_dir", nargs="?", help="Directory containing WSI pair folders.")
    parser.add_argument("output_dir", nargs="?", help="Root directory for aligned outputs.")
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
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Collect configuration through the historical prompts.",
    )


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Run alignment from parsed command-line arguments."""
    if args.interactive:
        return run_interactive()
    if not args.input_dir or not args.output_dir:
        parser.error("input_dir and output_dir are required unless --interactive is used")

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


def run_interactive() -> int:
    """Collect alignment settings with the historical interactive prompts."""
    from rocqipath.registration import AlignmentConfig, run_alignment

    print("\n" + "─" * 72)
    print("  Alignment Pipeline")
    print("─" * 72)
    print("  Register fixed / moving slide pairs and save aligned OME-TIFFs.")
    print("  Press Enter to accept defaults shown in [brackets].\n")

    input_dir = _get_existing_dir("  Input directory (contains pair folders): ")
    output_dir = _get_dir("  Output directory: ")
    raw_pairs = input("  Pair folders (comma-separated, or Enter for all): ").strip()
    pair_folders = [item.strip() for item in raw_pairs.split(",") if item.strip()]
    reference_name = input("  Reference folder/role name [reference]: ").strip() or "reference"
    moving_name = input("  Moving folder/role name [moving]: ").strip() or "moving"
    method = input("  Method — valis / orb [valis]: ").strip().lower() or "valis"
    if method not in ("valis", "orb"):
        print("  Unknown method — defaulting to valis.")
        method = "valis"

    config = AlignmentConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        pair_folders=pair_folders,
        reference_name=reference_name,
        moving_name=moving_name,
        alignment_method=method,
        aligned_wsi_level=_get_int("Aligned WSI pyramid level (0 = full res)", 0, 0),
        valis_max_error_um=_get_optional_float(
            "Max acceptable VALIS error in um (Enter = no limit)"
        ),
        qc_enabled=_get_bool("Save centre-patch QC PNG per case?", False),
        patch_size=_get_int("Patch size px", 1024, 1),
        grid_density=_get_int("Grid density rows", 1, 1),
        target_magnification=_get_float("Target magnification (physical x)", 20.0),
    )
    try:
        results = run_alignment(config)
        print(f"\n  Done - {len(results)} case(s) processed.")
        return 0
    except Exception as exc:
        logger.exception(f"Alignment pipeline failed: {exc}")
        return 1
