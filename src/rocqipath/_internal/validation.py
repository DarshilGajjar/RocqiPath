"""Reusable lightweight configuration validators."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Type


def require(
    condition: bool,
    message: str,
    *,
    exception_type: Type[Exception] = ValueError,
) -> None:
    """Raise ``exception_type`` with ``message`` unless ``condition`` holds."""
    if not condition:
        raise exception_type(message)


def validate_directory(value: str | Path, *, name: str, must_exist: bool = False) -> Path:
    """Resolve and validate a directory configuration value."""
    path = Path(value).expanduser().resolve()
    if must_exist and not path.is_dir():
        raise FileNotFoundError(f"{name} does not exist: {path}")
    return path


def validate_positive(
    value: float,
    *,
    name: str,
    message: str | None = None,
    exception_type: Type[Exception] = ValueError,
) -> float:
    """Return a positive number or raise the existing value-style error."""
    require(
        value > 0,
        message or f"{name} must be > 0",
        exception_type=exception_type,
    )
    return value


def validate_fraction(
    value: float,
    *,
    name: str,
    message: str | None = None,
    exception_type: Type[Exception] = ValueError,
) -> float:
    """Return a fraction in ``[0, 1]`` or raise ``ValueError``."""
    require(
        0.0 <= value <= 1.0,
        message or f"{name} must be in [0, 1]",
        exception_type=exception_type,
    )
    return value


def validate_choice(value: Any, *, name: str, choices: Iterable[Any]) -> Any:
    """Return a member of ``choices`` or raise ``ValueError``."""
    allowed = tuple(choices)
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}; got {value!r}")
    return value


__all__ = [
    "validate_choice",
    "validate_directory",
    "validate_fraction",
    "validate_positive",
    "require",
]
