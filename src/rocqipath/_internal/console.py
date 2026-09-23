"""Plain-text console and progress helpers."""

from __future__ import annotations

import getpass
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Iterable, Optional, Sequence

__all__ = [
    "ask",
    "print_banner",
    "print_code",
    "print_counts",
    "print_df",
    "print_dict",
    "print_done",
    "print_error",
    "print_info",
    "print_path",
    "print_rule",
    "print_section",
    "print_step",
    "print_summary_table",
    "print_tree",
    "print_warn",
    "prompt",
    "spinner",
    "status_context",
    "track",
]

_banner_printed = False


def print_banner(force: bool = False) -> None:
    """Print the application name once per process."""
    global _banner_printed
    if _banner_printed and not force:
        return
    _banner_printed = True
    print("\nRocqiPath\n" + "=" * 72)


def print_rule(title: str = "", style: str = "") -> None:
    """Print a plain horizontal divider with an optional title."""
    del style
    print(f"--- {title} " + "-" * max(0, 66 - len(title)) if title else "-" * 72)


def print_section(title: str) -> None:
    """Print a section heading."""
    print(f"\n{title}\n" + "-" * len(title))


def print_step(label: str, message: str = "", icon: str = "-") -> None:
    """Print a labelled pipeline step."""
    suffix = f" {message}" if message else ""
    print(f"{icon} [{label}]{suffix}")


def print_done(message: str, icon: str = "OK") -> None:
    """Print a success message."""
    print(f"{icon}: {message}")


def print_warn(message: str, icon: str = "WARNING") -> None:
    """Print a warning message to stderr."""
    print(f"{icon}: {message}", file=sys.stderr)


def print_error(message: str, icon: str = "ERROR") -> None:
    """Print an error message to stderr."""
    print(f"{icon}: {message}", file=sys.stderr)


def print_info(message: str, icon: str = "INFO") -> None:
    """Print an informational message."""
    print(f"{icon}: {message}")


def print_counts(ok: int, fail: int, label: str = "") -> None:
    """Print successful and failed item counts."""
    prefix = f"{label}: " if label else ""
    print(f"{prefix}{ok} ok, {fail} failed")


def print_summary_table(
    rows: Sequence[tuple[str, Any]],
    title: str = "Summary",
    key_header: str = "Field",
    val_header: str = "Value",
    float_fmt: str = ".4f",
) -> None:
    """Print a two-column plain-text summary."""
    rendered = [
        (str(key), format(value, float_fmt) if isinstance(value, float) else str(value))
        for key, value in rows
    ]
    key_width = max([len(key_header), *(len(key) for key, _ in rendered)])
    print_section(title)
    print(f"{key_header.ljust(key_width)}  {val_header}")
    print(f"{'-' * key_width}  {'-' * len(val_header)}")
    for key, value in rendered:
        print(f"{key.ljust(key_width)}  {value}")


def print_df(df: Any, title: str = "", max_rows: int = 20) -> None:
    """Print a dataframe-like value without a presentation library."""
    if title:
        print_section(title)
    head = getattr(df, "head", None)
    print(head(max_rows).to_string(index=False) if callable(head) else repr(df))


def print_dict(values: dict, title: str = "", depth: int = 0) -> None:
    """Print dictionary keys and values."""
    del depth
    print_summary_table(list(values.items()), title=title or "Dictionary")


def track(
    iterable: Iterable,
    description: str = "Processing...",
    total: Optional[int] = None,
) -> Iterable:
    """Wrap an iterable in the project's existing tqdm progress bar."""
    try:
        from tqdm.auto import tqdm
    except ImportError:
        return iterable
    return tqdm(iterable, desc=description, total=total)


@contextmanager
def spinner(description: str = "Working...") -> Generator[None, None, None]:
    """Print start and completion messages for an indeterminate operation."""
    print_step("RUN", description)
    try:
        yield None
    finally:
        print_done(description)


@contextmanager
def status_context(message: str) -> Generator[None, None, None]:
    """Print start, completion, and failure messages around an operation."""
    print_step("RUN", message)
    started = time.perf_counter()
    try:
        yield
        print_done(f"{message}  ({time.perf_counter() - started:.2f} s)")
    except Exception as exc:
        print_error(f"{message} - {exc}")
        raise


def print_code(code: str, language: str = "python", title: str = "", theme: str = "") -> None:
    """Print source text with an optional heading."""
    del language, theme
    if title:
        print_section(title)
    print(code)


def print_path(path: str | Path, label: str = "") -> None:
    """Print a path with a size or file-count annotation."""
    resolved = Path(path)
    detail = "not found"
    if resolved.is_file():
        detail = _human_size(resolved.stat().st_size)
    elif resolved.is_dir():
        detail = f"{sum(1 for item in resolved.rglob('*') if item.is_file())} files"
    prefix = f"{label}: " if label else ""
    print(f"{prefix}{resolved} ({detail})")


def print_tree(root: str | Path, max_depth: int = 2, show_size: bool = False) -> None:
    """Print a directory tree to ``max_depth``."""
    root = Path(root)
    if not root.exists():
        print_warn(f"Path not found: {root}")
        return
    print(root)
    for path in sorted(root.rglob("*"), key=lambda item: (len(item.parts), str(item).casefold())):
        depth = len(path.relative_to(root).parts)
        if depth > max_depth:
            continue
        suffix = f" ({_human_size(path.stat().st_size)})" if show_size and path.is_file() else ""
        marker = "/" if path.is_dir() else ""
        print(f"{'  ' * depth}{path.name}{marker}{suffix}")


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def ask(question: str, default: bool = True) -> bool:
    """Read a yes/no response, using ``default`` outside a terminal."""
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{question} {suffix} ").strip().lower()
    return default if not answer else answer in {"y", "yes"}


def prompt(question: str, default: str = "", password: bool = False) -> str:
    """Read a text response, using ``default`` outside a terminal."""
    if not sys.stdin.isatty():
        return default
    label = f"{question} [{default}]" if default else question
    answer = getpass.getpass(f"{label}: ") if password else input(f"{label}: ")
    return answer or default
