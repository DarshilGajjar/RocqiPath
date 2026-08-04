"""The ``rocqipath doctor`` command.

Prints the environment block that the bug-report template asks for: Python,
platform, native libvips and OpenSlide runtimes, installed optional extras,
and the resolved workspace root.
"""

from __future__ import annotations

import argparse
import json


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add diagnostics arguments to a command parser."""
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable output instead of the formatted report.",
    )


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Print environment diagnostics.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.
    parser : argparse.ArgumentParser
        Unused; present for the shared command signature.

    Returns
    -------
    int
        ``0`` when nothing is obviously wrong, ``1`` when problems were found.
    """
    from rocqipath.study.doctor import collect_diagnostics, format_diagnostics

    report = collect_diagnostics()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print("\n" + format_diagnostics(report) + "\n")
    return 1 if report.problems else 0
