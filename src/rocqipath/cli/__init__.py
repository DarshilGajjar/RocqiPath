"""Unified command-line interface for RocqiPath feature pipelines."""

from __future__ import annotations

import argparse
from typing import List, Optional


def build_parser() -> argparse.ArgumentParser:
    """Build the root parser and all feature subcommands."""
    from rocqipath.cli.commands import align, compare, count, extract, stain

    parser = argparse.ArgumentParser(
        prog="rocqipath",
        description="Whole-slide image processing for computational pathology.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Open the historical guided menu.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands = (
        ("align", "Register paired whole-slide images.", align),
        ("extract", "Extract WSI tissue regions or TMA cores.", extract),
        ("stain", "Train or apply a stain normalizer.", stain),
        ("count", "Count DAB-positive cells.", count),
        ("compare", "Create publication-quality WSI comparisons.", compare),
    )
    for name, help_text, module in commands:
        command_parser = subparsers.add_parser(
            name,
            help=help_text,
            description=help_text,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        module.configure_parser(command_parser)
        command_parser.set_defaults(_handler=module.run, _command_parser=command_parser)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Dispatch a subcommand or launch the guided menu when none is supplied."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interactive or args.command is None:
        from rocqipath.cli.legacy import main_menu

        try:
            main_menu()
            return 0
        except KeyboardInterrupt:
            print("\n  Interrupted by user.\n")
            return 130
    return int(args._handler(args, args._command_parser) or 0)


__all__ = ["build_parser", "main"]
