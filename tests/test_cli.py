"""Smoke coverage for the unified command-line parser."""

from __future__ import annotations

import argparse

import pytest

from rocqipath.cli import build_parser, main


def test_cli_exposes_one_subcommand_per_pipeline() -> None:
    """Keep the command surface explicit and stable."""
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    assert set(subparsers.choices) == {
        "study",
        "doctor",
        "align",
        "extract",
        "stain",
        "count",
        "compare",
    }


@pytest.mark.parametrize(
    "command", ["study", "doctor", "align", "extract", "stain", "count", "compare"]
)
def test_subcommand_help_exits_cleanly(command: str, capsys) -> None:
    """Ensure each command can show help without loading its optional backend."""
    with pytest.raises(SystemExit) as exc_info:
        main([command, "--help"])
    assert exc_info.value.code == 0
    assert f"usage: rocqipath {command}" in capsys.readouterr().out
