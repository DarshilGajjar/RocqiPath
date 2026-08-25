"""Plain-text configuration reporting helpers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Sequence

from rocqipath.core.console import print_summary_table


def print_config_panel(
    config: Any = None,
    *,
    title: str = "Configuration",
    extra: Mapping[str, Any] | None = None,
    rows: Sequence[tuple[str, Any]] | None = None,
) -> None:
    """Print configuration values as a two-column plain-text summary."""
    if rows is not None:
        display_rows = list(rows)
    elif hasattr(config, "describe") and callable(config.describe):
        display_rows = list(config.describe())
    elif is_dataclass(config) and not isinstance(config, type):
        display_rows = list(asdict(config).items())
    elif isinstance(config, Mapping):
        display_rows = list(config.items())
    elif config is None:
        display_rows = []
    else:
        display_rows = list(vars(config).items())

    if extra:
        display_rows = [*extra.items(), *display_rows]
    print_summary_table(
        [(str(key).replace("_", " ").title(), value) for key, value in display_rows],
        title=title,
    )


__all__ = ["print_config_panel"]
