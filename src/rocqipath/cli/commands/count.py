"""DAB-positive cell-counting command for the unified RocqiPath CLI."""

from __future__ import annotations

import argparse
import os


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add cell-counting arguments to a command parser."""
    parser.add_argument("input", help="Input WSI or directory of WSIs.")
    parser.add_argument("--pred", help="Prediction WSI for paired comparison mode.")
    parser.add_argument("-o", "--output-dir", default="./cell_count_output")
    parser.add_argument("--label", default="Cell")
    parser.add_argument("--patch-size", type=int, default=512)
    parser.add_argument("--tissue-threshold", type=float, default=0.10)
    parser.add_argument("--target-magnification", type=float, default=20.0)
    parser.add_argument("--source-magnification", type=float)
    parser.add_argument("--paired-source-magnification", type=float)
    parser.add_argument("--min-cell-area", type=int, default=50)
    parser.add_argument("--max-cell-area", type=int)
    parser.add_argument("--max-plots", type=int, default=10)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--no-plots", action="store_true")


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Count one slide, compare a pair, or count every slide in a directory."""
    if args.pred and os.path.isdir(args.input):
        parser.error("--pred cannot be combined with a directory input")

    from rocqipath.analysis import CellCountingConfig, PositiveCellCounter

    config = CellCountingConfig(
        patch_size=args.patch_size,
        tissue_threshold=args.tissue_threshold,
        target_magnification=args.target_magnification,
        source_magnification=args.source_magnification,
        paired_source_magnification=args.paired_source_magnification,
        output_dir=args.output_dir,
        min_cell_area=args.min_cell_area,
        max_cell_area=args.max_cell_area,
    )
    counter = PositiveCellCounter(config)
    if args.pred:
        counter.count_slide_pair(
            args.input,
            args.pred,
            label=args.label,
            save_plots=not args.no_plots,
            max_plots=args.max_plots,
            dpi=args.dpi,
        )
    elif os.path.isdir(args.input):
        counter.count_batch(args.input, label=args.label)
    else:
        counter.count_slide(args.input, label=args.label)
    return 0
