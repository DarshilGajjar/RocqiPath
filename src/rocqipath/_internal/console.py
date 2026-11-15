"""Plain-text console and progress helpers."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Any, Generator, Iterable, Optional, Sequence

__all__ = [
    "print_banner",
    "print_counts",
    "print_done",
    "print_error",
    "print_info",
    "print_section",
    "print_step",
    "print_summary_table",
    "print_warn",
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


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


