"""The ``rocqipath`` command line, generated from the workflow registry.

Every registered workflow becomes a subcommand taking the same inputs and
output folder as its Python function, plus one flag per config field::

    rocqipath <workflow> INPUT [INPUT ...] OUTPUT [--field VALUE ...]

Flag help comes from each config's docstring. Settings most users never
change are listed only by ``--help-all``; nested backend settings use a dot,
e.g. ``--valis.max-acceptable-error-um 100``. ``--config settings.toml``
loads a saved config, which explicit flags then override.

Utility commands: ``rocqipath list`` (workflows and whether their extra is
installed), ``rocqipath info SLIDE`` and ``rocqipath studio``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from rocqipath._internal.base_config import (
    NESTED_SEPARATOR,
    docstring_parameters,
    field_schema,
    summary_line,
)

_SCALARS = {"int": int, "float": float, "str": str}


def _flag(name: str, prefix: str = "") -> str:
    return "--" + prefix + name.replace("_", "-")


def _plain(text: str) -> str:
    """Drop reStructuredText markup for terminal help."""
    for markup in ("``", ":func:", ":class:", ":meth:"):
        text = text.replace(markup, "")
    return text.replace("`", "")


def _help(entry: Dict[str, Any], show_all: bool) -> str:
    if entry["advanced"] and not show_all:
        return argparse.SUPPRESS
    text = _plain(entry["help"] or "")
    if entry["default"] not in (None, "", [], {}):
        text += f" (default: {entry['default']})"
    return text.replace("%", "%%")


def _add_field(
    group: argparse._ArgumentGroup, entry: Dict[str, Any], show_all: bool, prefix: str = ""
) -> None:
    """Add one config field as a command-line flag."""
    dest = prefix.replace(".", NESTED_SEPARATOR) + entry["name"]
    flag = _flag(entry["name"], prefix)
    help_text = _help(entry, show_all)
    kind = entry["type"]
    if kind == "config":
        for sub in entry["fields"]:
            _add_field(group, {**sub, "advanced": True}, show_all, prefix=f"{prefix}{entry['name']}.")
        return
    common = {"dest": dest, "help": help_text, "default": argparse.SUPPRESS}
    if kind == "bool":
        group.add_argument(flag, action=argparse.BooleanOptionalAction, **common)
    elif kind == "choice":
        group.add_argument(flag, choices=entry["choices"], metavar="{" + ",".join(map(str, entry["choices"])) + "}", **common)
    elif kind in _SCALARS:
        group.add_argument(flag, type=_SCALARS[kind], metavar=kind.upper(), **common)
    elif kind == "list" and entry.get("items") in _SCALARS:
        nargs = entry.get("length") or "+"
        group.add_argument(
            flag, type=_SCALARS[entry["items"]], nargs=nargs, metavar=entry["items"].upper(), **common
        )
    else:  # mappings, lists of configs, arbitrary objects
        group.add_argument(flag, type=json.loads, metavar="JSON", **common)


def _add_workflow(subparsers, workflow, show_all: bool) -> None:
    parser = subparsers.add_parser(
        workflow.cli_name,
        help=workflow.summary,
        description=workflow.summary + f"\n\nNeeds: pip install rocqipath[{workflow.extra}]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT", help=f"Input: {workflow.inputs.kind}.")
    parser.add_argument("output_dir", metavar="OUTPUT", help="Folder for results.")
    parser.add_argument(
        "--config", dest="_config_file", type=Path, metavar="FILE", help="Load settings from a TOML file."
    )
    parser.add_argument("--help-all", action="store_true", dest="_help_all", help="Show every setting.")
    parser.add_argument("--debug", action="store_true", dest="_debug", help="Show full tracebacks.")
    if workflow.options:
        options = parser.add_argument_group("inputs")
        documented = docstring_parameters(workflow.function)
        for option in workflow.options:
            options.add_argument(
                _flag(option),
                dest=option,
                default=argparse.SUPPRESS,
                metavar="PATH",
                help=_plain(summary_line(documented.get(option, ""))),
            )
    settings = parser.add_argument_group(f"settings ({workflow.config.__name__})")
    for entry in field_schema(workflow.config):
        _add_field(settings, entry, show_all)
    parser.set_defaults(_workflow=workflow.name)


def build_parser(show_all: bool = False) -> argparse.ArgumentParser:
    """Build the root parser with one subcommand per registered workflow."""
    from rocqipath.registry import list_workflows

    parser = argparse.ArgumentParser(
        prog="rocqipath",
        description="Whole-slide image processing for computational pathology.",
    )
    parser.add_argument("--version", action="store_true", help="Print the version and exit.")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    listing = subparsers.add_parser("list", help="List workflows and whether their extras are installed.")
    listing.set_defaults(_utility="list")
    info = subparsers.add_parser("info", help="Show a slide's dimensions, levels and magnification.")
    info.add_argument("slide")
    info.set_defaults(_utility="info")
    studio = subparsers.add_parser("studio", help="Start the local browser workspace.")
    studio.add_argument("--port", type=int, default=8765)
    studio.add_argument("--workspace", type=Path, default=Path.home() / "RocqiPathStudio")
    studio.add_argument("--static-dir", type=Path)
    studio.set_defaults(_utility="studio")
    for workflow in list_workflows():
        _add_workflow(subparsers, workflow, show_all)
    return parser


def _run_utility(args: argparse.Namespace) -> int:
    if args._utility == "list":
        from rocqipath.extras import missing_modules
        from rocqipath.registry import list_workflows

        for workflow in list_workflows():
            missing = missing_modules(workflow.extra)
            status = "ready" if not missing else f"needs rocqipath[{workflow.extra}]"
            print(f"{workflow.cli_name:<24} {status:<30} {workflow.summary}")
        return 0
    if args._utility == "info":
        from rocqipath.io.slide import open_slide

        with open_slide(args.slide) as slide:
            properties = slide.properties
            print(f"file        : {args.slide}")
            print(f"dimensions  : {slide.dimensions[0]} x {slide.dimensions[1]}")
            print(f"levels      : {len(slide.level_downsamples)} {tuple(round(d, 2) for d in slide.level_downsamples)}")
            print(f"objective   : {properties.get('openslide.objective-power', 'unknown')}")
            print(f"microns/px  : {properties.get('openslide.mpp-x', 'unknown')}")
        return 0
    from rocqipath.studio.__main__ import serve

    return serve(args.port, args.workspace, args.static_dir)


def _run_workflow(args: argparse.Namespace) -> int:
    from rocqipath.registry import get_workflow

    workflow = get_workflow(args._workflow)
    params = {
        key: value for key, value in vars(args).items()
        if not key.startswith("_") and key not in {"inputs", "output_dir", "command", "version"}
    }
    if args._config_file is not None:
        params["config"] = workflow.config.from_toml(args._config_file)
    inputs = args.inputs if len(args.inputs) > 1 else args.inputs[0]
    result = workflow.function(inputs, args.output_dir, **params)
    roles: Dict[str, int] = {}
    for item in result:
        roles[item.role] = roles.get(item.role, 0) + 1
    produced = ", ".join(f"{count} {role}" for role, count in sorted(roles.items())) or "nothing"
    print(f"\n{workflow.cli_name}: produced {produced} in {result.output_dir}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Parse arguments and run a workflow or utility command."""
    try:
        return _main(argv)
    except BrokenPipeError:  # output piped into e.g. `head`; exit quietly
        import os

        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


def _main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    show_all = "--help-all" in argv
    if show_all:
        argv = [arg if arg != "--help-all" else "--help" for arg in argv]
    parser = build_parser(show_all=show_all)
    args = parser.parse_args(argv)
    if args.version:
        from rocqipath import __version__

        print(__version__)
        return 0
    if args.command is None:
        parser.print_help()
        return 2
    if getattr(args, "_utility", None):
        return _run_utility(args)
    try:
        return _run_workflow(args)
    except Exception as exc:  # present errors as messages, not tracebacks
        if args._debug:
            raise
        print(f"rocqipath {args.command}: error: {exc}", file=sys.stderr)
        return 1


__all__ = ["build_parser", "main"]
