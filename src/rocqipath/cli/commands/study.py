"""The ``rocqipath study`` command group.

One study, one directory, no path arguments.  The subcommands follow the same
order as the model itself: ``init`` writes the descriptor, ``index`` finds the
slides, ``survey`` measures them, ``verify`` reports problems, ``plan``
resolves a recipe, ``run`` executes stages, ``select`` applies QC rules, and
``results`` prints the tidy table.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from rocqipath.core.exceptions import WSIProcessingError

_SUBCOMMANDS = (
    "init",
    "index",
    "survey",
    "verify",
    "plan",
    "run",
    "select",
    "results",
    "list",
    "show",
)


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Attach every study subcommand to ``parser``."""
    parser.add_argument(
        "--home",
        help="Workspace root. Defaults to $ROCQIPATH_HOME, then ~/rocqipath.",
    )
    subparsers = parser.add_subparsers(dest="study_command", metavar="SUBCOMMAND")

    init = subparsers.add_parser("init", help="Create a study and write study.toml.")
    init.add_argument("name", help="Study name.")
    init.add_argument(
        "--source",
        action="append",
        default=[],
        dest="sources",
        help="Slide directory to search. Repeatable.",
    )
    init.add_argument(
        "--stain",
        action="append",
        default=[],
        dest="stains",
        help="Stain key. The first becomes the reference stain. Repeatable.",
    )
    init.add_argument("--magnification", type=float, default=20.0)
    init.add_argument("--overwrite", action="store_true")

    index = subparsers.add_parser("index", help="Discover slides and write index.jsonl.")
    index.add_argument("name")
    index.add_argument(
        "--no-stat",
        action="store_true",
        help="Skip size/mtime/digest reads. Faster on slow network storage.",
    )

    survey = subparsers.add_parser("survey", help="Measure every indexed slide.")
    survey.add_argument("name")
    survey.add_argument("--quiet", action="store_true", help="Suppress per-slide progress.")

    verify = subparsers.add_parser("verify", help="Report problems before running anything.")
    verify.add_argument("name")
    verify.add_argument("--json", action="store_true", help="Emit machine-readable output.")

    plan = subparsers.add_parser("plan", help="Resolve settings and write recipe.json.")
    plan.add_argument("name")
    plan.add_argument(
        "--set",
        action="append",
        default=[],
        dest="settings",
        metavar="STAGE.KEY=VALUE",
        help="Override one resolved setting, e.g. patches.patch_size=256. Repeatable.",
    )

    run = subparsers.add_parser("run", help="Execute one stage or the whole pipeline.")
    run.add_argument("name")
    run.add_argument(
        "--stage",
        action="append",
        default=[],
        dest="stages",
        help="Stage to run. Repeatable. Defaults to every stage.",
    )
    run.add_argument("--dry-run", action="store_true", help="Report the plan, execute nothing.")
    run.add_argument(
        "--link-mode",
        choices=("auto", "symlink", "hardlink", "copy"),
        default="auto",
        help="How staged inputs are materialised for directory-based pipelines.",
    )
    run.add_argument("--continue-on-error", action="store_true")

    select = subparsers.add_parser("select", help="Save a named QC view over a manifest.")
    select.add_argument("name")
    select.add_argument("selection_name", help="Name for the selection.")
    select.add_argument("--stage", default="patches")
    select.add_argument("--manifest", help="Manifest base name. Defaults to the stage name.")
    select.add_argument(
        "--rule",
        default="",
        help="Rule expression, e.g. \"tissue_fraction >= 0.6 and blur >= percentile('blur', 10)\".",
    )
    select.add_argument(
        "--min",
        action="append",
        default=[],
        dest="minimums",
        metavar="FIELD=VALUE",
        help="Convenience minimum threshold. Repeatable.",
    )

    results = subparsers.add_parser("results", help="Print an aggregated result table.")
    results.add_argument("name")
    results.add_argument("--stage", default="counts")
    results.add_argument("--manifest")
    results.add_argument("--selection")
    results.add_argument("--group-by", default="case,stain")
    results.add_argument("--csv", help="Also write the table to this CSV path.")
    results.add_argument("--limit", type=int, default=20)

    show = subparsers.add_parser("show", help="Print a short summary of a study.")
    show.add_argument("name")

    subparsers.add_parser("list", help="List studies in the workspace.")


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Dispatch a study subcommand.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.
    parser : argparse.ArgumentParser
        The study command parser, used for usage errors.

    Returns
    -------
    int
        Process exit code.
    """
    command = getattr(args, "study_command", None)
    if command is None:
        parser.print_help()
        return 1
    if command not in _SUBCOMMANDS:  # pragma: no cover - argparse rejects these first
        parser.error(f"Unknown study subcommand: {command}")

    handler = globals()[f"_cmd_{command}"]
    try:
        return int(handler(args) or 0)
    except WSIProcessingError as exc:
        print(f"\n  {type(exc).__name__}: {exc}\n")
        return 1


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------
def _open(args: argparse.Namespace):
    """Open the study named on the command line."""
    from rocqipath.study import Study

    return Study.open(args.name, home=getattr(args, "home", None))


def _cmd_init(args: argparse.Namespace) -> int:
    """Create a study directory and descriptor."""
    from rocqipath.study import Study

    stains = args.stains or ["he", "cd8"]
    study = Study.create(
        args.name,
        sources=args.sources,
        stains=stains,
        home=args.home,
        default_magnification=args.magnification,
        overwrite=args.overwrite,
    )
    print(f"\n  Created study: {study.root}")
    print(f"  Descriptor:    {study.paths.descriptor}")
    if not args.sources:
        print("\n  Next: edit the [[sources]] root in study.toml, then run:")
    else:
        print("\n  Next:")
    print(f"    rocqipath study index {args.name}")
    print(f"    rocqipath study survey {args.name}")
    print(f"    rocqipath study verify {args.name}\n")
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    """Discover slides and write the index."""
    study = _open(args)
    records = study.index(stat_files=not args.no_stat)
    stains: dict = {}
    for record in records:
        stains[record.stain] = stains.get(record.stain, 0) + 1
    print(f"\n  Indexed {len(records)} slide(s) across {len(study.cases())} case(s).")
    for stain, count in sorted(stains.items()):
        print(f"    {stain:<12} {count}")
    print(f"    pairs        {len(study.pairs())}")
    for warning in study.index_warnings[:10]:
        print(f"    warning: {warning}")
    if len(study.index_warnings) > 10:
        print(f"    ... {len(study.index_warnings) - 10} more warning(s)")
    print(f"\n  Wrote {study.paths.index}\n")
    return 0


def _cmd_survey(args: argparse.Namespace) -> int:
    """Measure every indexed slide."""
    study = _open(args)

    def progress(position: int, total: int, item) -> None:
        """Print one line per surveyed slide."""
        state = "ok" if item.readable else "UNREADABLE"
        magnification = (
            f"{item.base_magnification:g}x" if item.base_magnification else "no metadata"
        )
        print(f"    [{position}/{total}] {item.slide_uid:<40} {magnification:<14} {state}")

    survey = study.survey(progress=None if args.quiet else progress)
    summary = survey.summary()
    print(f"\n  Surveyed {summary['n_slides']} slide(s).")
    print(f"    readable                {summary['n_readable']}")
    print(f"    missing magnification   {summary['n_missing_magnification']}")
    print(f"    below target            {summary['n_below_target']}")
    print(f"    magnifications          {summary['magnification_histogram']}")
    print(f"\n  Wrote {study.paths.survey}\n")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """Report problems that would break a run."""
    study = _open(args)
    report = study.verify()
    if args.json:
        print(
            json.dumps(
                {
                    "study": report.study,
                    "ok": report.ok,
                    "checked": report.checked,
                    "issues": [
                        {
                            "severity": item.severity,
                            "scope": item.scope,
                            "message": item.message,
                            "fix": item.fix,
                        }
                        for item in report.issues
                    ],
                },
                indent=2,
            )
        )
    else:
        print("\n" + report.format() + "\n")
    return 0 if report.ok else 1


def _parse_settings(pairs: List[str]) -> dict:
    """Parse ``STAGE.KEY=VALUE`` overrides into a nested mapping."""
    overrides: dict = {}
    for item in pairs:
        if "=" not in item or "." not in item.split("=", 1)[0]:
            raise ValueError(f"Expected STAGE.KEY=VALUE, got {item!r}")
        target, raw = item.split("=", 1)
        stage, key = target.split(".", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        overrides.setdefault(stage, {})[key] = value
    return overrides


def _cmd_plan(args: argparse.Namespace) -> int:
    """Resolve settings and write the recipe."""
    study = _open(args)
    try:
        overrides = _parse_settings(args.settings)
    except ValueError as exc:
        print(f"\n  {exc}\n")
        return 1
    recipe = study.plan(overrides=overrides or None)
    print(f"\n  Wrote {study.paths.recipe}")
    print(f"  Recipe hash: {recipe.recipe_hash}")
    from rocqipath.study.stages import STAGE_ORDER

    print("\n  Stages:")
    for stage in STAGE_ORDER:
        settings = recipe.stages.get(stage, {})
        state = "enabled" if settings.get("enabled", True) else "disabled"
        print(f"    {stage:<12} {state}")
    if recipe.notes:
        print("\n  Notes:")
        for note in recipe.notes[:10]:
            print(f"    - {note}")
        if len(recipe.notes) > 10:
            print(f"    ... {len(recipe.notes) - 10} more")
    print()
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Execute one or more stages."""
    study = _open(args)
    results = study.run(
        args.stages or None,
        dry_run=args.dry_run,
        link_mode=args.link_mode,
        stop_on_error=not args.continue_on_error,
    )
    print()
    failed = 0
    for result in results:
        print(f"  {result.stage:<12} {result.status:<10} items={result.n_items}")
        for warning in result.warnings:
            print(f"      warning: {warning}")
        if result.error:
            failed += 1
            print(f"      error:   {result.error}")
    print()
    return 1 if failed else 0


def _cmd_select(args: argparse.Namespace) -> int:
    """Save a named QC view over a stage manifest."""
    study = _open(args)
    thresholds = {}
    for item in args.minimums:
        if "=" not in item:
            print(f"\n  Expected FIELD=VALUE, got {item!r}\n")
            return 1
        key, raw = item.split("=", 1)
        try:
            thresholds[key] = float(raw)
        except ValueError:
            print(f"\n  Threshold for {key!r} must be numeric, got {raw!r}\n")
            return 1
    selection = study.select(
        args.selection_name,
        stage=args.stage,
        rule=args.rule,
        manifest=args.manifest,
        **thresholds,
    )
    kept = selection.fraction_kept * 100.0
    print(f"\n  Selection: {selection.name}")
    print(f"    rule       {selection.rule or '(everything)'}")
    print(f"    stage      {selection.stage}")
    print(f"    kept       {selection.n_selected} / {selection.n_input}  ({kept:.1f}%)")
    for field_name, stats in sorted(selection.stats.items()):
        print(
            f"    {field_name:<14} "
            f"min={stats['min']:.4g} median={stats['median']:.4g} max={stats['max']:.4g}"
        )
    print(f"\n  Wrote {study.paths.selections / (selection.name + '.json')}\n")
    return 0


def _cmd_results(args: argparse.Namespace) -> int:
    """Print an aggregated result table."""
    study = _open(args)
    table = study.results(
        stage=args.stage,
        manifest=args.manifest,
        selection=args.selection,
        group_by=tuple(item.strip() for item in args.group_by.split(",") if item.strip()),
    )
    print("\n" + table.format(limit=args.limit) + "\n")
    if args.csv:
        written = table.to_csv(Path(args.csv))
        print(f"  Wrote {written}\n")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    """Print a short summary of one study."""
    study = _open(args)
    summary = study.summary()
    print()
    for key, value in summary.items():
        label = key.replace("_", " ")
        print(f"  {label:<18} {value}")
    print()
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List every study in the workspace."""
    from rocqipath.study import resolve_home

    home = resolve_home(getattr(args, "home", None))
    if not home.is_dir():
        print(f"\n  No workspace at {home}. Create a study with: rocqipath study init <name>\n")
        return 0
    studies = sorted(
        path.name for path in home.iterdir() if path.is_dir() and (path / "study.toml").is_file()
    )
    print(f"\n  Workspace: {home}")
    if not studies:
        print("  (no studies yet)\n")
        return 0
    for name in studies:
        print(f"    {name}")
    print()
    return 0


def _optional(value: Optional[str]) -> Optional[str]:
    """Return a stripped string, or ``None`` when empty."""
    return value.strip() if value and value.strip() else None
