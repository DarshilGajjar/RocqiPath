"""Predictable output-layout helpers for all RocqiPath modules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Union

__all__ = ["OutputLayout", "safe_name"]


def safe_name(value: str) -> str:
    """Return a filesystem-safe name while preserving readable identifiers."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    if not cleaned:
        raise ValueError("Output name becomes empty after sanitization")
    return cleaned


@dataclass(frozen=True)
class OutputLayout:
    """Build the standard ``<root>/<module>/<item>`` output hierarchy.

    This intentionally limits nesting to two predictable levels beneath the
    caller-provided root. All artifacts for one input slide/case live together
    in its item directory.
    """

    root: Union[str, Path]

    def module_dir(self, module_name: str, *, create: bool = True) -> Path:
        """Return ``<root>/<module_name>`` and optionally create it."""
        path = Path(self.root).expanduser().resolve() / safe_name(module_name)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def item_dir(self, module_name: str, item_name: str, *, create: bool = True) -> Path:
        """Return ``<root>/<module_name>/<item_name>`` and optionally create it."""
        path = self.module_dir(module_name, create=create) / safe_name(item_name)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path
