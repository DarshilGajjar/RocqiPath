"""Reusable lightweight configuration validators."""

from __future__ import annotations

from typing import Type


def require(
    condition: bool,
    message: str,
    *,
    exception_type: Type[Exception] = ValueError,
) -> None:
    """Raise ``exception_type`` with ``message`` unless ``condition`` holds."""
    if not condition:
        raise exception_type(message)


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


__all__ = [
    "validate_fraction",
    "validate_positive",
    "require",
]
