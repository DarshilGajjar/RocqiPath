"""The command line is generated from the workflow registry."""

from __future__ import annotations

import argparse

import pytest

import rocqipath as rp
from rocqipath.cli import build_parser, main

WORKFLOW_COMMANDS = sorted(w.cli_name for w in rp.list_workflows())


def _subcommands(parser: argparse.ArgumentParser) -> set:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return set(action.choices)


def test_every_workflow_has_a_command_plus_utilities() -> None:
    assert _subcommands(build_parser()) == {*WORKFLOW_COMMANDS, "list", "info", "studio"}


@pytest.mark.parametrize("command", WORKFLOW_COMMANDS)
def test_workflow_help_exits_cleanly(command: str, capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([command, "--help"])
    assert exc_info.value.code == 0
    assert f"usage: rocqipath {command}" in capsys.readouterr().out


@pytest.mark.parametrize("workflow", rp.list_workflows(), ids=lambda w: w.name)
def test_help_shows_every_basic_setting(workflow, capsys) -> None:
    from rocqipath._internal.base_config import field_schema

    with pytest.raises(SystemExit):
        main([workflow.cli_name, "--help"])
    out = capsys.readouterr().out
    for entry in field_schema(workflow.config):
        flag = "--" + entry["name"].replace("_", "-")
        if entry["advanced"]:
            assert flag + " " not in out
        else:
            assert flag in out


def test_help_all_reveals_advanced_and_nested_settings(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["align", "--help-all"])
    out = capsys.readouterr().out
    assert "--grid-density" in out
    assert "--valis.max-acceptable-error-um" in out
    assert "--orb.ransac-threshold" in out


def test_flags_parse_into_config_fields() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["extract-tissue", "in", "out", "--detector", "semantic", "--semantic-device", "cpu"]
    )
    assert (args.detector, args.semantic_device) == ("semantic", "cpu")
    assert not hasattr(args, "target_magnification")  # unset flags do not override
    nested = parser.parse_args(["align", "a", "b", "--valis.num-features", "3000", "--no-qc-enabled"])
    assert (nested.valis__num_features, nested.qc_enabled) == (3000, False)


def test_list_reports_each_workflow(capsys) -> None:
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    for command in WORKFLOW_COMMANDS:
        assert command in out


def test_errors_are_reported_without_traceback(tmp_path, capsys) -> None:
    code = main(["count-cells", str(tmp_path / "missing.tif"), str(tmp_path / "out"), "--patch-size", "-1"])
    assert code == 1
    assert "rocqipath count-cells: error:" in capsys.readouterr().err


def test_no_command_prints_help(capsys) -> None:
    assert main([]) == 2
    assert "usage: rocqipath" in capsys.readouterr().out
