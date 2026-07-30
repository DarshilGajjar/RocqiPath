"""Generic Rich configuration and summary reporting helpers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Sequence

from rocqipath.core.console import console


def print_config_panel(
    config: Any = None,
    *,
    title: str = "Configuration",
    extra: Mapping[str, Any] | None = None,
    rows: Sequence[tuple[str, Any]] | None = None,
) -> None:
    """Render any dataclass or mapping as a two-column Rich panel."""
    from rich.panel import Panel
    from rich.table import Table

    if rows is not None:
        display_rows = list(rows)
    else:
        if hasattr(config, "describe") and callable(config.describe):
            display_rows = list(config.describe())
            if extra:
                display_rows = [
                    (
                        str(key).replace("_", " ").title(),
                        value,
                    )
                    for key, value in extra.items()
                ] + display_rows
            values = {}
        elif is_dataclass(config) and not isinstance(config, type):
            values = asdict(config)
        elif isinstance(config, Mapping):
            values = dict(config)
        elif config is None:
            values = {}
        else:
            values = vars(config)
        if extra:
            values = {**dict(extra), **values}
        if not (hasattr(config, "describe") and callable(getattr(config, "describe", None))):
            display_rows = [
                (str(key).replace("_", " ").title(), value) for key, value in values.items()
            ]
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold white", no_wrap=True)
    table.add_column("Value", style="bright_cyan")
    for key, value in display_rows:
        table.add_row(str(key), str(value))
    console.print(Panel(table, title=f"[bold green]{title}[/]", expand=False))


__all__ = ["print_config_panel"]
