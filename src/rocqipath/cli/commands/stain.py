"""Stain-normalization command for the unified RocqiPath CLI."""

from __future__ import annotations

import argparse
from typing import List, Optional

from rocqipath.cli.prompts import (
    _get_bool,
    _get_dir,
    _get_existing_dir,
    _get_float,
    _get_int,
    _get_stain_list,
)
from rocqipath.core.console import print_error, print_warn
from rocqipath.core.exceptions import ConfigurationError, DependencyError, ExtractionError


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add stain-normalization arguments to a command parser."""
    parser.add_argument("--mode", required=True, choices=("train", "apply"))
    parser.add_argument("-i", "--in-dir", "--in_dir", required=True, metavar="DIR")
    parser.add_argument(
        "-o",
        "--out-dir",
        "--out_dir",
        default="./results/normalization",
        metavar="DIR",
    )
    parser.add_argument("-w", "--weights", metavar="FILE")
    parser.add_argument("-s", "--stains", default="he", metavar="STAIN[,STAIN…]")
    parser.add_argument(
        "--n-type",
        "--n_type",
        dest="n_type",
        required=True,
        choices=("reinhard", "macenko", "vahadane"),
    )
    parser.add_argument(
        "--fit-min-tissue",
        "--fit_min_tissue",
        type=float,
        default=0.1,
        metavar="FRAC",
    )
    parser.add_argument(
        "--max-train-patches",
        "--max_train_patches",
        type=int,
        default=1000,
        metavar="N",
    )
    parser.add_argument("--resume", action="store_true")


def run(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> int:
    """Train or apply a stain normalizer from parsed arguments."""
    from rocqipath.stain import (
        StainNormalizationConfig,
        run_stain_normalization_apply,
        run_stain_normalization_train,
    )

    try:
        config = StainNormalizationConfig(
            n_type=args.n_type,
            stains=args.stains,
            fit_min_tissue=args.fit_min_tissue,
            max_train_patches=args.max_train_patches,
            resume=args.resume,
            weights_path=args.weights,
        )
        if args.mode == "train":
            run_stain_normalization_train(args.in_dir, args.out_dir, config)
        else:
            run_stain_normalization_apply(args.in_dir, args.out_dir, config)
        return 0
    except (ConfigurationError, ExtractionError, DependencyError) as exc:
        print_error(str(exc))
        return 1
    except KeyboardInterrupt:
        print_warn("Interrupted by user.")
        return 130


def run_interactive() -> int:
    """Collect and run stain-normalization settings interactively."""
    from rocqipath.stain import (
        StainNormalizationConfig,
        run_stain_normalization_apply,
        run_stain_normalization_train,
    )

    print("\n" + "─" * 72)
    print("  Stain Normalization")
    print("─" * 72)
    mode = input("  Mode — train / apply [train]: ").strip().lower() or "train"
    if mode not in ("train", "apply"):
        print("  Unknown mode — defaulting to train.")
        mode = "train"
    input_dir = _get_existing_dir("  Input directory: ")
    output_dir = _get_dir("  Output directory: ")
    n_type = (
        input("  Algorithm — reinhard / macenko / vahadane [macenko]: ").strip().lower()
        or "macenko"
    )
    stains = _get_stain_list("Stain folder tokens, e.g. he")
    if mode == "train":
        config = StainNormalizationConfig(
            n_type=n_type,
            stains=stains,
            fit_min_tissue=_get_float("Min tissue fraction to use a patch [0-1]", 0.1),
            max_train_patches=_get_int(
                "Max patches for mosaic (Macenko/Vahadane)",
                1000,
                1,
            ),
        )
        run_stain_normalization_train(input_dir, output_dir, config)
    else:
        config = StainNormalizationConfig(
            n_type=n_type,
            stains=stains,
            resume=_get_bool("Skip patches already normalised (resume)?", False),
        )
        run_stain_normalization_apply(input_dir, output_dir, config)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Run the standalone stain command used by the legacy module shim."""
    parser = argparse.ArgumentParser(
        prog="stain_normalization",
        description="Batch H&E stain normalisation (Reinhard / Macenko / Vahadane).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    configure_parser(parser)
    return run(parser.parse_args(argv), parser)
