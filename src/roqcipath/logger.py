"""
roqcipath.logger
=====================
Rich-based logging, display, progress, and timing utilities for the
``roqcipath`` library and every script that builds on it.

This module is entirely self-contained — it has no imports from other
``roqcipath`` submodules, so it can be imported first, before anything
else, without circular-import risk.

────────────────────────────────────────────────────────────────────────────────
QUICK REFERENCE
────────────────────────────────────────────────────────────────────────────────

  # Recommended import style — grab only what you need
  from roqcipath.logger import (
      logger, get_logger,
      print_banner, print_rule, print_section,
      print_step, print_done, print_warn, print_error, print_info,
      print_summary_table, print_df, print_dict,
      track, make_progress, spinner,
      Timer, timed, status_context,
      print_code, print_path, print_tree,
      ask, prompt,
      print_counts, log_exception,
      set_log_level, install_traceback,
      console,
  )

  # Or use the module object directly
  from roqcipath import logger as L
  L.print_banner()
  L.logger.info("Registering slide pair")

────────────────────────────────────────────────────────────────────────────────
FULL API
────────────────────────────────────────────────────────────────────────────────

  SINGLETONS ──────────────────────────────────────────────────────────────────
  console                   Rich Console (theme-aware; use instead of print())
  logger                    loguru Logger (single system for entire library)

  LOGGER HELPERS ──────────────────────────────────────────────────────────────
  get_logger(name)          child logger namespaced as roqcipath.<name>
  set_log_level(level)      change level at runtime  ("DEBUG", "INFO", …)
  install_traceback()       replace default exception hook with Rich tracebacks
  log_exception(exc, label) log an exception + traceback at ERROR level

  BANNER / LAYOUT ─────────────────────────────────────────────────────────────
  print_banner()                    WSI logo in a bordered panel (no labels)
  print_rule(title, style)          ─── full-width divider ───
  print_section(title)              bold section header + rule

  STEP OUTPUT ─────────────────────────────────────────────────────────────────
  print_step(label, msg)    •  [LABEL]  message
  print_done(msg)           ✔  green success line
  print_warn(msg)           ⚠  yellow warning line
  print_error(msg)          ✘  red error line
  print_info(msg)           ℹ  dim informational line
  print_counts(ok, fail)    ✔ N ok   ✘ M failed summary

  TABLES ──────────────────────────────────────────────────────────────────────
  print_summary_table(rows) two-column key / value rounded table
  print_df(df, title)       pandas DataFrame → Rich table (soft dependency)
  print_dict(d, title)      any dict → Rich table with optional nested expansion

  PROGRESS ────────────────────────────────────────────────────────────────────
  track(iterable, desc)     simple for-loop progress bar (replaces tqdm)
  make_progress()           context-managed multi-task bar with ETA columns
  spinner(desc)             context-managed animated spinner

  TIMING ──────────────────────────────────────────────────────────────────────
  Timer(label)              context manager AND decorator — logs elapsed time
  timed(label)              @timed("label") shorthand decorator

  STATUS ──────────────────────────────────────────────────────────────────────
  status_context(msg)       prints step on entry, done/error + elapsed on exit

  CODE / FILE DISPLAY ─────────────────────────────────────────────────────────
  print_code(code, lang)    syntax-highlighted code / JSON / YAML block
  print_path(path, label)   file or directory path with size annotation
  print_tree(root, depth)   directory tree via rich.tree

  INTERACTIVE ─────────────────────────────────────────────────────────────────
  ask(question, default)    yes / no confirmation prompt  → bool
  prompt(question, default) text input prompt             → str

────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import functools
import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import (
    Any, Callable, Generator, Iterable,
    List, Optional, Tuple, Union,
)

from rich import box
from rich.console import Console
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler
from rich.markup import escape as _escape   # safely renders ASCII art with \ chars
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
from rich.traceback import install as _install_traceback
from rich.tree import Tree

# ── version mirrors the parent package ───────────────────────────────────────
try:
    from roqcipath import __version__ as _PKG_VERSION
except Exception:
    _PKG_VERSION = "?"

__all__ = [
    # singletons
    "console", "logger",
    # logger helpers
    "get_logger", "set_log_level", "add_log_file",
    "install_traceback", "log_exception",
    # banner / layout
    "print_banner", "print_rule", "print_section",
    # step output
    "print_step", "print_done", "print_warn", "print_error",
    "print_info", "print_counts",
    # tables
    "print_summary_table", "print_df", "print_dict",
    # progress
    "track", "make_progress", "spinner",
    # timing
    "Timer", "timed", "status_context",
    # code / file
    "print_code", "print_path", "print_tree",
    # interactive
    "ask", "prompt",
]

# ══════════════════════════════════════════════════════════════════════════════
# THEME
# ══════════════════════════════════════════════════════════════════════════════

_THEME = Theme({
    # output categories
    "banner":               "bold cyan",
    "step":                 "bold white",
    "step.label":           "bold cyan",
    "done":                 "bold green",
    "warn":                 "bold yellow",
    "error":                "bold red",
    "info":                 "dim white",
    "meta":                 "dim cyan",
    "section.title":        "bold cyan",
    # progress
    "progress.description": "cyan",
    "progress.percentage":  "bold cyan",
    "bar.complete":         "cyan",
    "bar.finished":         "green",
    "bar.pulse":            "cyan",
    # table / code
    "table.header":         "bold cyan",
    "table.border":         "cyan",
    "code.border":          "dim cyan",
})

# ══════════════════════════════════════════════════════════════════════════════
# CONSOLE SINGLETON
# ══════════════════════════════════════════════════════════════════════════════

console = Console(theme=_THEME, highlight=False, markup=True)
"""
Shared Rich ``Console`` for the entire ``roqcipath`` library.
Use instead of ``print()`` so all output respects the project theme.

    from roqcipath.logger import console
    console.print("[bold cyan]Hello[/bold cyan]")
"""

# ══════════════════════════════════════════════════════════════════════════════
# LOGGING  — loguru as the single log system for the entire library
# ══════════════════════════════════════════════════════════════════════════════

from loguru import logger as _loguru_logger  # noqa: E402

# Remove the default loguru handler and install one clean stderr sink.
# All modules import `logger` from here — one system, one format, everywhere.
_loguru_logger.remove()
_loguru_logger.add(
    sys.stderr,
    level    = "DEBUG",
    format   = (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "{message}"
    ),
    colorize = True,
)

logger = _loguru_logger
"""
Loguru logger for the entire ``roqcipath`` library.

Every module imports this single object — one system, one format:

    from roqcipath.logger import logger
    logger.info("Registering slide pair: {}", case_id)
    logger.debug("pyvips | {} {}×{}", name, w, h)
    logger.warning("Core count mismatch — falling back to H&E")
    logger.error("Missing H&E slide — skipping block")
    logger.success("Extraction complete — {} cores saved", n)
"""


def get_logger(name: str):
    """
    Return the shared library logger bound with a module tag.

    The returned object is the same loguru logger — ``name`` is stored as
    extra context so structured log sinks can filter by module if needed.

        from roqcipath.logger import get_logger
        _log = get_logger("core")
        _log.info("Registering {}", case_id)

    Parameters
    ----------
    name : str
        Sub-module tag, e.g. ``"core"``, ``"alignment"``, ``"extraction"``.
    """
    return logger.bind(module=name)


def set_log_level(level: str) -> None:
    """
    Change the log level for all roqcipath output at runtime.

        from roqcipath.logger import set_log_level
        set_log_level("DEBUG")    # show all messages
        set_log_level("WARNING")  # only warnings and above

    Parameters
    ----------
    level : str   ``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ``"ERROR"``
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level    = level.upper(),
        format   = (
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "{message}"
        ),
        colorize = True,
    )
    logger.debug("Log level → {}", level.upper())


def add_log_file(path: str, *, level: str = "DEBUG") -> None:
    """
    Write log output to a file in addition to stderr.

    Safe to call multiple times — each call adds a new file sink.

        from roqcipath.logger import add_log_file
        add_log_file("./output/run.log")
        add_log_file("./output/errors.log", level="WARNING")

    Parameters
    ----------
    path  : str   destination file path (parent directories are created)
    level : str   minimum level for this sink (default ``"DEBUG"``)
    """
    import pathlib
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        path,
        level    = level.upper(),
        format   = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        encoding = "utf-8",
        rotation = None,
    )


def install_traceback(show_locals: bool = False) -> None:
    """
    Replace Python's default exception hook with a Rich traceback.

        from roqcipath.logger import install_traceback
        install_traceback()
        install_traceback(True)   # also show local variables

    Parameters
    ----------
    show_locals : bool
        Print local variables for every stack frame when ``True``.
    """
    _install_traceback(console=console, show_locals=show_locals)


def log_exception(exc: BaseException, label: str = "") -> None:
    """
    Log an exception at ERROR level and print a Rich traceback.

        try:
            register_slides()
        except Exception as e:
            log_exception(e, "registration failed")

    Parameters
    ----------
    exc   : BaseException
    label : str   optional context string prepended to the message
    """
    prefix = f"{label}: " if label else ""
    logger.error("{}{}", prefix, exc)
    console.print_exception(show_locals=False)


# ══════════════════════════════════════════════════════════════════════════════
# BANNER
# ══════════════════════════════════════════════════════════════════════════════

_ASCII = (
    "  ██╗    ██╗  ███████╗  ██╗\n"
    "  ██║    ██║  ██╔════╝  ██║\n"
    "  ██║ █╗ ██║  ███████╗  ██║\n"
    "  ██║███╗██║  ╚════██║  ██║\n"
    "  ╚███╔███╔╝  ███████║  ██║\n"
    "   ╚══╝╚══╝   ╚══════╝  ╚═╝"
)

# Tracks whether the banner has already been printed this session.
# Set to True after the first call to print_banner() or any pipeline entry point.
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


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# STEP / STATUS OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

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
    """Print a green success line.  ✔  <message>"""
    console.print(f"[done]{icon}  {message}[/done]")


def print_warn(message: str, icon: str = "\u26a0") -> None:
    """Print a yellow warning line.  ⚠  <message>"""
    console.print(f"[warn]{icon}  {message}[/warn]")


def print_error(message: str, icon: str = "\u2718") -> None:
    """Print a red error line.  ✘  <message>"""
    console.print(f"[error]{icon}  {message}[/error]")


def print_info(message: str, icon: str = "\u2139") -> None:
    """Print a dim informational line.  ℹ  <message>"""
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
    prefix   = Text(f"{label}  ", style="step") if label else Text()
    ok_t     = Text(f"\u2714  {ok} ok",      style="done")
    fail_t   = Text(f"   \u2718  {fail} failed", style="error" if fail else "info")
    line     = prefix
    line.append_text(ok_t)
    line.append_text(fail_t)
    console.print(line)


# ══════════════════════════════════════════════════════════════════════════════
# TABLES
# ══════════════════════════════════════════════════════════════════════════════

def print_summary_table(
    rows:       List[Tuple[str, Any]],
    title:      str = "Summary",
    key_header: str = "Field",
    val_header: str = "Value",
    float_fmt:  str = ".4f",
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
        title        = title,
        box          = box.ROUNDED,
        border_style = "cyan",
        title_style  = "bold cyan",
        show_lines   = True,
        highlight    = False,
    )
    tbl.add_column(key_header, style="meta",       no_wrap=True,  min_width=22)
    tbl.add_column(val_header, style="bold white",  no_wrap=False)
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
        title        = title or "DataFrame",
        box          = box.SIMPLE_HEAVY,
        border_style = "cyan",
        title_style  = "bold cyan",
        show_lines   = False,
        highlight    = False,
    )
    for col in df.columns:
        tbl.add_column(str(col), style="white", no_wrap=True)
    for _, row in df.head(max_rows).iterrows():
        tbl.add_row(*[str(v) for v in row])
    if len(df) > max_rows:
        tbl.add_row(*[
            f"... ({len(df) - max_rows} more)" if i == 0 else "..."
            for i in range(len(df.columns))
        ])
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
        title        = title or "Dict",
        box          = box.ROUNDED,
        border_style = "cyan",
        title_style  = "bold cyan",
        show_lines   = True,
        highlight    = False,
    )
    tbl.add_column("Key",   style="meta",       no_wrap=True,  min_width=18)
    tbl.add_column("Value", style="bold white",  no_wrap=False)

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
            return "  ".join(
                f"[meta]{k}[/meta]: {_fmt(vv, rem - 1)}" for k, vv in v.items()
            )
        return f"{v:.4f}" if isinstance(v, float) else str(v)

    for k, v in d.items():
        tbl.add_row(str(k), _fmt(v, depth))
    console.print(tbl)


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS
# ══════════════════════════════════════════════════════════════════════════════

def track(
    iterable:    Iterable,
    description: str = "Processing...",
    total:       Optional[int] = None,
) -> Iterable:
    """
    Simple for-loop progress bar — drop-in replacement for ``tqdm``.

        from roqcipath.logger import track
        for slide in track(slides, "Registering slides"):
            register(slide)

    Parameters
    ----------
    iterable    : any iterable
    description : label shown left of the bar
    total       : explicit total for generators / unknown-length iterables
    """
    return _rich_track(
        iterable,
        description = f"[progress.description]{description}[/]",
        total       = total,
        console     = console,
    )


def make_progress() -> Progress:
    """
    Return a configured ``rich.Progress`` context manager with ETA columns.

    Use when you need multiple tasks or fine-grained advance control:

        from roqcipath.logger import make_progress
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
            bar_width      = None,
            style          = "bar.complete",
            complete_style = "bar.complete",
            finished_style = "bar.finished",
        ),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console   = console,
        expand    = True,
        transient = False,
    )


@contextmanager
def spinner(description: str = "Working...") -> Generator[Status, None, None]:
    """
    Context manager showing an animated spinner for indeterminate tasks.

    Use when you cannot measure progress (large file reads, network calls …):

        from roqcipath.logger import spinner
        with spinner("Loading BioFormats metadata..."):
            metadata = reader.get_metadata()

    Parameters
    ----------
    description : str   message shown next to the spinner
    """
    with console.status(
        f"[progress.description]{description}[/]",
        spinner       = "dots",
        spinner_style = "cyan",
    ) as st:
        yield st


# ══════════════════════════════════════════════════════════════════════════════
# TIMING
# ══════════════════════════════════════════════════════════════════════════════

class Timer:
    """
    Context manager **and** decorator that logs elapsed wall-clock time.

    Context manager
    ---------------
        from roqcipath.logger import Timer
        with Timer("VALIS registration"):
            registrar.register()
        # → DEBUG  ⏱  VALIS registration — 12.34 s

    Decorator
    ---------
        @Timer("warp_slide")
        def warp_slide(slide_obj, level=0):
            ...

    Parameters
    ----------
    label   : str
        Description logged with the elapsed time.
    logger_ : logging.Logger, optional
        Logger to write the timing to.  Defaults to the ``roqcipath``
        root logger.  Pass ``None`` to use ``print_info`` instead.
    level   : int
        Log level for the timing message (default ``logging.DEBUG``).
    """

    def __init__(
        self,
        label:   str = "Task",
        logger_: Optional[logging.Logger] = None,
        level:   int = logging.DEBUG,
    ) -> None:
        """Store the timing configuration; the clock starts on ``__enter__``.

        Parameters
        ----------
        label : str, optional
            Description logged alongside the elapsed time. Defaults to
            ``"Task"``. When used as a decorator (see :meth:`__call__`)
            and ``label`` is falsy, the wrapped function's ``__name__``
            is used instead.
        logger_ : logging.Logger, optional
            Logger to write the timing message to via
            :meth:`logging.Logger.log`. Defaults to the module-level
            ``roqcipath`` logger. Pass ``None`` explicitly to fall back to
            :func:`console.print` instead of the logging system.
        level : int, optional
            Log level (from the :mod:`logging` module) for the timing
            message. Defaults to ``logging.DEBUG`` so routine timings
            don't clutter INFO-level output.
        """
        self.label   = label
        self._log    = logger_ if logger_ is not None else logger
        self._level  = level
        self._start: float = 0.0

    def __enter__(self) -> "Timer":
        """Record the start time and return ``self`` for the ``with`` block.

        Returns
        -------
        Timer
            This instance, enabling ``with Timer("label") as t:`` should
            callers want access to the timer object inside the block
            (though typically it is unused).
        """
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        """Compute the elapsed time since ``__enter__`` and log it.

        Parameters
        ----------
        *_ : Any
            The standard ``(exc_type, exc_value, traceback)`` triple
            passed by the context-manager protocol. Ignored — the elapsed
            time is logged unconditionally, whether or not the ``with``
            block raised, since timing information is useful either way.
        """
        self._emit(time.perf_counter() - self._start)

    def __call__(self, func: Callable) -> Callable:
        """Wrap ``func`` so every call logs its own elapsed execution time.

        Enables using a ``Timer`` instance as a decorator:
        ``@Timer("label")`` above a function definition.

        Parameters
        ----------
        func : Callable
            The function to wrap. Its signature is preserved via
            :func:`functools.wraps`.

        Returns
        -------
        Callable
            A wrapper function with the same signature as ``func`` that
            times each invocation and logs it under ``self.label`` (or
            ``func.__name__`` if ``self.label`` is falsy), then returns
            ``func``'s original return value unchanged.
        """
        lbl = self.label or func.__name__

        @functools.wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            """Call the wrapped function, timing and logging its execution.

            Parameters
            ----------
            *args, **kwargs
                Forwarded verbatim to the wrapped function.

            Returns
            -------
            Any
                Whatever the wrapped function returns, unmodified.
            """
            t0     = time.perf_counter()
            result = func(*args, **kwargs)
            self._emit(time.perf_counter() - t0, label=lbl)
            return result

        return _wrapper

    def _emit(self, elapsed: float, label: Optional[str] = None) -> None:
        """Format an elapsed duration as a human-readable string and log it.

        Parameters
        ----------
        elapsed : float
            Elapsed time in seconds (as returned by
            :func:`time.perf_counter` differences).
        label : str, optional
            Override for ``self.label`` used just for this call — used by
            the decorator path (:meth:`__call__`) where each wrapped
            function needs its own name instead of the ``Timer``
            instance's shared label. When omitted, ``self.label`` is used.

        Notes
        -----
        The duration is scaled for readability: minutes when
        ``elapsed >= 60``, seconds when ``elapsed >= 1``, otherwise
        milliseconds. The formatted message is sent to ``self._log`` (via
        :meth:`logging.Logger.log` at ``self._level``) if a logger was
        configured, otherwise printed directly via :func:`console.print`.
        """
        lbl = label or self.label
        if elapsed >= 60:
            human = f"{elapsed / 60:.1f} min"
        elif elapsed >= 1:
            human = f"{elapsed:.2f} s"
        else:
            human = f"{elapsed * 1000:.1f} ms"
        msg = f"[meta]\u23f1  {lbl}[/meta] \u2014 [bold white]{human}[/bold white]"
        if self._log:
            self._log.log(self._level, msg)
        else:
            console.print(msg)


def timed(label: str = "") -> Callable:
    """
    Decorator factory that logs elapsed time for the decorated function.

    Shorthand for ``@Timer(label)``:

        from roqcipath.logger import timed

        @timed("patch extraction")
        def extract_patches(slide, level=2):
            ...

    Parameters
    ----------
    label : str   description; defaults to the function name when empty
    """
    def _decorator(func: Callable) -> Callable:
        """Apply a :class:`Timer` to ``func`` using the enclosing ``label``.

        Parameters
        ----------
        func : Callable
            The function being decorated by ``@timed(label)``.

        Returns
        -------
        Callable
            The timed wrapper produced by ``Timer(...).__call__(func)`` —
            see :meth:`Timer.__call__`.
        """
        return Timer(label=label or func.__name__)(func)
    return _decorator


# ══════════════════════════════════════════════════════════════════════════════
# STATUS CONTEXT
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def status_context(message: str) -> Generator[None, None, None]:
    """
    Context manager that emits a step line on entry and a done / error on exit.

        from roqcipath.logger import status_context
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


# ══════════════════════════════════════════════════════════════════════════════
# CODE / FILE DISPLAY
# ══════════════════════════════════════════════════════════════════════════════

def print_code(
    code:     str,
    language: str = "python",
    title:    str = "",
    theme:    str = "monokai",
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
        title        = title or f"[dim]{language}[/dim]",
        border_style = "code.border",
        padding      = (0, 1),
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
    p      = Path(path)
    exists = p.exists()
    icon   = "\U0001f4c4" if p.is_file() else ("\U0001f4c1" if p.is_dir() else "?")
    size   = (
        _human_size(p.stat().st_size)      if p.is_file()
        else f"{sum(1 for _ in p.rglob('*'))} files" if p.is_dir()
        else "not found"
    )
    colour = "green" if exists else "red"
    prefix = f"[meta]{label}[/meta]  " if label else ""
    console.print(
        f"{prefix}[{colour}]{icon}  {p}[/{colour}]  [dim]({size})[/dim]"
    )


def print_tree(
    root:      Union[str, Path],
    max_depth: int  = 2,
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
        guide_style = "dim cyan",
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
                sz = (
                    f"  [dim]{_human_size(child.stat().st_size)}[/dim]"
                    if show_size else ""
                )
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


# ══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

def ask(question: str, default: bool = True) -> bool:
    """
    Interactive yes / no confirmation prompt.

    Returns ``True`` for yes, ``False`` for no.
    Falls back to ``default`` automatically when stdin is not a TTY
    (non-interactive / CI environments):

        from roqcipath.logger import ask
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

        from roqcipath.logger import prompt
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
        default  = default or None,
        password = password,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST   python -m roqcipath.logger
# ══════════════════════════════════════════════════════════════════════════════

def _demo() -> None:
    """Visual demo of every public function — run to verify the install."""
    print_banner()

    print_rule("Layout")
    print_section("Section Header")

    print_rule("Step Output")
    print_step("SCAN",  "Scanning ./data/wsi ...")
    print_step("WARP",  "Warping slide at level 2")
    print_step("SAVE",  "Writing OME-TIFF ...")
    print_info("Using pyramid level 2 (ds=4.00x)")
    print_done("PDF saved -> ./alignment_report.pdf")
    print_warn("sample_003: no side-by-side image found")
    print_error("sample_007: warp failed")
    print_counts(ok=11, fail=1, label="Registration")

    print_rule("Logger")
    set_log_level("DEBUG")
    logger.debug("Debug message")
    logger.info("Info with [bold]markup[/bold]")
    logger.warning("Warning message")
    logger.error("Error message")
    get_logger("core").info("Child logger: [bold]roqcipath.core[/bold]")
    get_logger("alignment").info("Child logger: [bold]roqcipath.alignment[/bold]")
    set_log_level("INFO")

    print_rule("Tables")
    print_summary_table([
        ("Samples",      12),
        ("Biomarkers",   "marker_A, marker_B, marker_C"),
        ("Error (um)",   47.0123),
        ("Level",        2),
        ("Output",       "./alignment_report.pdf"),
    ], title="Registration Results")

    print_dict(
        {"slide_dims": (5506, 4627), "level": 2, "ds": 4.0,
         "meta": {"units": "um", "resolution": 0.25}},
        title="Slide Metadata",
        depth=1,
    )

    print_rule("Progress")
    for _ in track(range(6), "Processing slides"):
        time.sleep(0.04)

    with make_progress() as prog:
        t1 = prog.add_task("Warping ...",  total=5)
        t2 = prog.add_task("Saving ...",   total=5)
        for _ in range(5):
            time.sleep(0.05); prog.advance(t1)
        for _ in range(5):
            time.sleep(0.03); prog.advance(t2)

    with spinner("Loading BioFormats metadata ..."):
        time.sleep(0.5)

    print_rule("Timing")
    set_log_level("DEBUG")

    with Timer("Registration block"):
        time.sleep(0.1)

    @timed("warp_slide")
    def _fake_warp():
        """Sleep briefly to simulate a slow operation, for the @timed demo.

        Purely illustrative — stands in for a real function like an image
        warp, so :func:`timed`'s decorator behaviour can be demonstrated
        without depending on any actual imaging code in this self-test.
        """
        time.sleep(0.07)

    _fake_warp()
    set_log_level("INFO")

    print_rule("status_context")
    with status_context("Saving OME-TIFF"):
        time.sleep(0.08)

    print_rule("Code / File Display")
    print_code(
        "from roqcipath.logger import print_banner, track, Timer\n"
        'print_banner()',
        language = "python",
        title    = "Quick-start",
    )
    print_path(__file__, label="This module")
    print_tree(Path(__file__).parent, max_depth=1, show_size=True)

    print_rule()
    print_done(f"Self-test complete  |  roqcipath {_PKG_VERSION}")


if __name__ == "__main__":
    _demo()