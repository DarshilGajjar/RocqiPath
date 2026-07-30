"""Compatibility façade for :mod:`rocqipath.core.logging` and console helpers."""

from __future__ import annotations

from .core.console import *  # noqa: F403
from .core.console import __all__ as _console_all
from .core.logging import *  # noqa: F403
from .core.logging import __all__ as _logging_all

__all__ = [*_logging_all, *_console_all]
