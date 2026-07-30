"""Rich console, progress, display, and interactive helpers."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Iterable, List, Optional, Tuple, Union

from rich import box
from rich.console import Console
from rich.markup import escape as _escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    track as _rich_track,
)
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.tree import Tree

__all__ = [
    "console",
    "print_banner",
    "print_rule",
    "print_section",
    "print_step",
    "print_done",
    "print_warn",
    "print_error",
    "print_info",
    "print_counts",
    "print_summary_table",
    "print_df",
    "print_dict",
    "track",
    "make_progress",
    "spinner",
    "status_context",
    "print_code",
    "print_path",
    "print_tree",
    "ask",
    "prompt",
]


_THEME = Theme(
    {
        # output categories
        "banner": "bold cyan",
        "step": "bold white",
        "step.label": "bold cyan",
        "done": "bold green",
        "warn": "bold yellow",
        "error": "bold red",
        "info": "dim white",
        "meta": "dim cyan",
        "section.title": "bold cyan",
        # progress
        "progress.description": "cyan",
        "progress.percentage": "bold cyan",
        "bar.complete": "cyan",
        "bar.finished": "green",
        "bar.pulse": "cyan",
        # table / code
        "table.header": "bold cyan",
        "table.border": "cyan",
        "code.border": "dim cyan",
    }
)


console = Console(theme=_THEME, highlight=False, markup=True)


_ASCII = (
    "  ██╗    ██╗  ███████╗  ██╗\n"
    "  ██║    ██║  ██╔════╝  ██║\n"
    "  ██║ █╗ ██║  ███████╗  ██║\n"
    "  ██║███╗██║  ╚════██║  ██║\n"
    "  ╚███╔███╔╝  ███████║  ██║\n"
    "   ╚══╝╚══╝   ╚══════╝  ╚═╝"
)


_banner_printed: bool = False


def print_banner(force: bool = False) -> None:
    """
    Print the WSI block-letter logo inside a bordered panel.

    The banner is printed **at most once per session** — subsequent calls
    are silently ignored unless ``force=True``. Every pipeline module calls
    this automatically at import time, so the banner always appears first
    regardless of which function the user calls.

    The panel intentionally carries no title, subtitle, or timestamp — just
    the logo and its border.

    Parameters
    ----------
    force : bool  print even if the banner has already been shown
    """
    global _banner_printed
    if _banner_printed and not force:
        return
    _banner_printed = True

    art_text = Text(_escape(_ASCII), style="banner", justify="center")
    panel = Panel(
        art_text,
        border_style="cyan",
        padding=(1, 2),
        expand=True,
    )
    console.print()
    console.print(panel)
    console.print()


def print_rule(title: str = "", style: str = "cyan") -> None:
    """
    Print a full-width horizontal rule with an optional centred title.

        print_rule("Loading slides")
        print_rule()                      # plain divider
        print_rule("Complete", style="green")

    Parameters
    ----------
    title : str   centred label (empty → plain line)
    style : str   Rich colour / style string
    """
    console.print(Rule(title=title, style=style))


def print_section(title: str) -> None:
    """
    Print a bold cyan section header followed by a rule.

    Use for major pipeline phases:

        print_section("Rigid Registration")
        print_section("Patch Extraction")

    Parameters
    ----------
    title : str   section name
    """
    console.print()
    console.print(f"[section.title]{title}[/section.title]")
    console.print(Rule(style="cyan"))


def print_step(label: str, message: str = "", icon: str = "\u2022") -> None:
    """
    Print a labelled pipeline step line.

        print_step("SCAN",  "Scanning ./data/wsi ...")
        print_step("WARP",  "Warping slide at level 2")
        print_step("SAVE",  "Writing OME-TIFF ...")

    Parameters
    ----------
    label   : str   short ALL-CAPS tag, e.g. ``"SCAN"``, ``"WARP"``, ``"SAVE"``
    message : str   free-form detail text
    icon    : str   leading character (default ``•``)
    """
    line = Text()
    line.append(f"{icon}  ", style="step.label")
    line.append(f"[{label}]", style="step.label")
    if message:
        line.append(f"  {message}", style="step")
    console.print(line)


def print_done(message: str, icon: str = "\u2714") -> None:
    """Print a green success line.  ✔  <message>."""
    console.print(f"[done]{icon}  {message}[/done]")


def print_warn(message: str, icon: str = "\u26a0") -> None:
    """Print a yellow warning line.  ⚠  <message>."""
    console.print(f"[warn]{icon}  {message}[/warn]")


def print_error(message: str, icon: str = "\u2718") -> None:
    """Print a red error line.  ✘  <message>."""
    console.print(f"[error]{icon}  {message}[/error]")


def print_info(message: str, icon: str = "\u2139") -> None:
    """Print a dim informational line.  ℹ  <message>."""
    console.print(f"[info]{icon}  {message}[/info]")


def print_counts(ok: int, fail: int, label: str = "") -> None:
    """
    Print a compact ok / failed summary line.

        print_counts(11, 1, "Registration")
        # Registration  ✔  11 ok   ✘  1 failed

    Parameters
    ----------
    ok    : int   number of successful items
    fail  : int   number of failed items
    label : str   optional prefix description
    """
    prefix = Text(f"{label}  ", style="step") if label else Text()
    ok_t = Text(f"\u2714  {ok} ok", style="done")
    fail_t = Text(f"   \u2718  {fail} failed", style="error" if fail else "info")
    line = prefix
    line.append_text(ok_t)
    line.append_text(fail_t)
    console.print(line)


def print_summary_table(
    rows: List[Tuple[str, Any]],
    title: str = "Summary",
    key_header: str = "Field",
    val_header: str = "Value",
    float_fmt: str = ".4f",
) -> None:
    """
    Print a two-column key / value summary table.

        print_summary_table([
            ("Samples",    12),
            ("Biomarkers", "marker_A, marker_B"),
            ("Error (um)", 9.0123),
        ], title="Registration Results")

    Parameters
    ----------
    rows       : list of ``(key, value)`` tuples — any value type is accepted
    title      : str   table heading
    key_header : str   left column header  (default ``"Field"``)
    val_header : str   right column header (default ``"Value"``)
    float_fmt  : str   ``format()`` spec for float values (default ``".4f"``)
    """
    tbl = Table(
        title=title,
        box=box.ROUNDED,
        border_style="cyan",
        title_style="bold cyan",
        show_lines=True,
        highlight=False,
    )
    tbl.add_column(key_header, style="meta", no_wrap=True, min_width=22)
    tbl.add_column(val_header, style="bold white", no_wrap=False)
    for k, v in rows:
        if isinstance(v, float):
            v = format(v, float_fmt)
        tbl.add_row(str(k), str(v))
    console.print(tbl)


def print_df(df: Any, title: str = "", max_rows: int = 20) -> None:
    """
    Pretty-print a pandas ``DataFrame`` as a Rich table.

    Pandas is a **soft** dependency — falls back to ``repr()`` gracefully.

        print_df(error_df, title="Registration Errors", max_rows=10)

    Parameters
    ----------
    df       : pd.DataFrame
    title    : str   optional table heading
    max_rows : int   truncate when the frame has more rows (default 20)
    """
    try:
        import pandas as _pd

        if not isinstance(df, _pd.DataFrame):
            raise TypeError
    except (ImportError, TypeError):
        console.print(repr(df))
        return

    tbl = Table(
        title=title or "DataFrame",
        box=box.SIMPLE_HEAVY,
        border_style="cyan",
        title_style="bold cyan",
        show_lines=False,
        highlight=False,
    )
    for col in df.columns:
        tbl.add_column(str(col), style="white", no_wrap=True)
    for _, row in df.head(max_rows).iterrows():
        tbl.add_row(*[str(v) for v in row])
    if len(df) > max_rows:
        tbl.add_row(
            *[
                f"... ({len(df) - max_rows} more)" if i == 0 else "..."
                for i in range(len(df.columns))
            ]
        )
    console.print(tbl)


def print_dict(d: dict, title: str = "", depth: int = 0) -> None:
    """
    Pretty-print any dictionary as a Rich table.

    Nested dicts are expanded up to ``depth`` levels:

        print_dict(
            {"dims": (5506, 4627), "level": 2,
             "meta": {"units": "um", "ds": 4.0}},
            title="Slide Info",
            depth=1,           # expand one level of nested dicts
        )

    Parameters
    ----------
    d     : dict
    title : str   optional heading
    depth : int   nesting levels to expand inline (0 = top-level only)
    """
    tbl = Table(
        title=title or "Dict",
        box=box.ROUNDED,
        border_style="cyan",
        title_style="bold cyan",
        show_lines=True,
        highlight=False,
    )
    tbl.add_column("Key", style="meta", no_wrap=True, min_width=18)
    tbl.add_column("Value", style="bold white", no_wrap=False)

    def _fmt(v: Any, rem: int) -> str:
        """Format one dict value for table display, recursing into nested dicts.

        Parameters
        ----------
        v : Any
            The value to format — a nested dict, a float, or anything
            else (formatted via ``str()``).
        rem : int
            Remaining recursion depth. When ``v`` is a dict and
            ``rem > 0``, its items are rendered inline as
            ``key: value`` pairs (recursing with ``rem - 1``); once
            ``rem`` reaches ``0``, nested dicts fall through to the plain
            ``str(v)`` branch instead of expanding further, bounding how
            deep the inline rendering can go.

        Returns
        -------
        str
            A Rich-markup-formatted string: either a joined list of
            ``[meta]key[/meta]: value`` fragments (for an expandable
            dict), a value formatted to 4 decimal places (for a float),
            or ``str(v)`` for anything else.
        """
        if isinstance(v, dict) and rem > 0:
            return "  ".join(f"[meta]{k}[/meta]: {_fmt(vv, rem - 1)}" for k, vv in v.items())
        return f"{v:.4f}" if isinstance(v, float) else str(v)

    for k, v in d.items():
        tbl.add_row(str(k), _fmt(v, depth))
    console.print(tbl)


def track(
    iterable: Iterable,
    description: str = "Processing...",
    total: Optional[int] = None,
) -> Iterable:
    """Track an iterable with a simple for-loop progress bar.

    This is a drop-in replacement for ``tqdm``.

    Parameters
    ----------
    iterable    : any iterable
    description : label shown left of the bar
    total       : explicit total for generators / unknown-length iterables
    """
    return _rich_track(
        iterable,
        description=f"[progress.description]{description}[/]",
        total=total,
        console=console,
    )


def make_progress() -> Progress:
    """
    Return a configured ``rich.Progress`` context manager with ETA columns.

    Use when you need multiple tasks or fine-grained advance control:

        from rocqipath.logger import make_progress
        with make_progress() as prog:
            warp_task = prog.add_task("Warping slides...", total=n)
            save_task = prog.add_task("Saving OME-TIFFs...", total=n)
            for slide in slides:
                warp(slide);  prog.advance(warp_task)
                save(slide);  prog.advance(save_task)

    Returns
    -------
    rich.progress.Progress
    """
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(
            bar_width=None,
            style="bar.complete",
            complete_style="bar.complete",
            finished_style="bar.finished",
        ),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=True,
        transient=False,
    )


@contextmanager
def spinner(description: str = "Working...") -> Generator[Status, None, None]:
    """
    Context manager showing an animated spinner for indeterminate tasks.

    Use when you cannot measure progress (large file reads, network calls …):

        from rocqipath.logger import spinner
        with spinner("Loading BioFormats metadata..."):
            metadata = reader.get_metadata()

    Parameters
    ----------
    description : str   message shown next to the spinner
    """
    with console.status(
        f"[progress.description]{description}[/]",
        spinner="dots",
        spinner_style="cyan",
    ) as st:
        yield st


@contextmanager
def status_context(message: str) -> Generator[None, None, None]:
    """
    Context manager that emits a step line on entry and a done / error on exit.

        from rocqipath.logger import status_context
        with status_context("Saving OME-TIFF"):
            slide_obj.warp_and_save_slide(dst_f)
        # success → ✔  Saving OME-TIFF  (2.34 s)
        # failure → ✘  Saving OME-TIFF — <error message>
        #              (exception is re-raised)

    Parameters
    ----------
    message : str   short description of the operation
    """
    print_step("RUN", message)
    t0 = time.perf_counter()
    try:
        yield
        print_done(f"{message}  ({time.perf_counter() - t0:.2f} s)")
    except Exception as exc:
        print_error(f"{message} \u2014 {exc}")
        raise


def print_code(
    code: str,
    language: str = "python",
    title: str = "",
    theme: str = "monokai",
) -> None:
    """
    Print a syntax-highlighted code block inside a panel.

        print_code(open("config.py").read(), title="config.py")
        print_code(json.dumps(meta, indent=2), language="json", title="metadata")

    Parameters
    ----------
    code     : str   source text to display
    language : str   Pygments language id: ``"python"``, ``"json"``, ``"bash"`` …
    title    : str   optional panel title
    theme    : str   Pygments colour theme: ``"monokai"``, ``"dracula"`` …
    """
    panel = Panel(
        Syntax(code, language, theme=theme, line_numbers=True, word_wrap=False),
        title=title or f"[dim]{language}[/dim]",
        border_style="code.border",
        padding=(0, 1),
    )
    console.print(panel)


def print_path(path: Union[str, Path], label: str = "") -> None:
    """
    Pretty-print a file or directory path with size / file-count annotation.

        print_path("./output/alignment_report.pdf", label="PDF report")
        print_path("./data/wsi",                    label="Input root")

    Parameters
    ----------
    path  : str or Path
    label : str   optional prefix label
    """
    p = Path(path)
    exists = p.exists()
    icon = "\U0001f4c4" if p.is_file() else ("\U0001f4c1" if p.is_dir() else "?")
    size = (
        _human_size(p.stat().st_size)
        if p.is_file()
        else f"{sum(1 for _ in p.rglob('*'))} files"
        if p.is_dir()
        else "not found"
    )
    colour = "green" if exists else "red"
    prefix = f"[meta]{label}[/meta]  " if label else ""
    console.print(f"{prefix}[{colour}]{icon}  {p}[/{colour}]  [dim]({size})[/dim]")


def print_tree(
    root: Union[str, Path],
    max_depth: int = 2,
    show_size: bool = False,
) -> None:
    """
    Print a directory tree.

        print_tree("./data/wsi",        max_depth=3)
        print_tree("./output/aligned",  show_size=True)

    Parameters
    ----------
    root      : str or Path   root directory
    max_depth : int           levels to traverse (default 2)
    show_size : bool          show file sizes next to filenames (default False)
    """
    root = Path(root)
    if not root.exists():
        print_warn(f"Path not found: {root}")
        return
    tree = Tree(
        f"[bold cyan]{root.name}[/bold cyan]  [dim]{root}[/dim]",
        guide_style="dim cyan",
    )

    def _add(node: Tree, path: Path, depth: int) -> None:
        """Recursively populate a Rich ``Tree`` node with ``path``'s children.

        Parameters
        ----------
        node : rich.tree.Tree
            The tree node to attach ``path``'s children under.
        path : Path
            The directory whose contents should be added as children of
            ``node``.
        depth : int
            Current recursion depth (1 for the root's direct children).
            Recursion stops once ``depth > max_depth`` (captured from the
            enclosing :func:`print_tree` call), bounding how deep the
            tree is expanded.

        Notes
        -----
        Children are sorted with directories before files (via
        ``key=lambda p: (p.is_file(), p.name)``, which places non-files
        first since ``False < True``), and alphabetically by name within
        each group. Directories recurse via a fresh call to ``_add``;
        files are added as leaf nodes, optionally annotated with a
        human-readable size (see ``show_size`` on the enclosing
        :func:`print_tree`) computed by :func:`_human_size`.
        :class:`PermissionError` on ``path.iterdir()`` is caught silently
        so one unreadable directory doesn't abort printing the rest of
        the tree.
        """
        if depth > max_depth:
            return
        try:
            children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        for child in children:
            if child.is_dir():
                _add(node.add(f"[cyan]{child.name}/[/cyan]"), child, depth + 1)
            else:
                sz = f"  [dim]{_human_size(child.stat().st_size)}[/dim]" if show_size else ""
                node.add(f"[white]{child.name}[/white]{sz}")

    _add(tree, root, 1)
    console.print(tree)


def _human_size(n: int) -> str:
    """Format a byte count as a human-readable size string.

    Repeatedly divides ``n`` by 1024, stepping through the units
    B → KB → MB → GB → TB, until the value is under 1024 in the current
    unit (or TB is exhausted, in which case PB is used regardless of
    magnitude).

    Parameters
    ----------
    n : int
        Size in bytes. Expected to be non-negative (as returned by e.g.
        :meth:`os.stat_result.st_size`); negative input is not validated
        and would produce a nonsensical result.

    Returns
    -------
    str
        The size formatted to one decimal place with its unit suffix,
        e.g. ``"512.0 B"``, ``"3.4 MB"``, ``"1.2 GB"``.
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def ask(question: str, default: bool = True) -> bool:
    """
    Interactive yes / no confirmation prompt.

    Returns ``True`` for yes, ``False`` for no.
    Falls back to ``default`` automatically when stdin is not a TTY
    (non-interactive / CI environments):

        from rocqipath.logger import ask
        if not ask("Overwrite existing output?"):
            sys.exit(0)

    Parameters
    ----------
    question : str    question text
    default  : bool   answer used when running non-interactively
    """
    if not sys.stdin.isatty():
        return default
    return Confirm.ask(f"[bold cyan]{question}[/bold cyan]", default=default)


def prompt(question: str, default: str = "", password: bool = False) -> str:
    """
    Interactive text prompt.

    Falls back to ``default`` when stdin is not a TTY:

        from rocqipath.logger import prompt
        out_dir = prompt("Output directory", default="./output")
        token   = prompt("API token", password=True)

    Parameters
    ----------
    question : str    question text
    default  : str    value returned in non-interactive mode
    password : bool   mask the input characters
    """
    if not sys.stdin.isatty():
        return default
    return Prompt.ask(
        f"[bold cyan]{question}[/bold cyan]",
        default=default or None,
        password=password,
    )
