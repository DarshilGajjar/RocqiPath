"""Regression tests for native console and stdlib logging infrastructure."""

from __future__ import annotations

import logging

import rocqipath.core.console as core_console
import rocqipath.core.logging as core_logging


def test_spinner_remains_a_context_manager(capsys) -> None:
    """The plain-text spinner keeps the context-manager protocol."""
    with core_console.spinner("synthetic") as status:
        assert status is None

    output = capsys.readouterr().out
    assert "[RUN] synthetic" in output
    assert "OK: synthetic" in output


def test_status_context_preserves_success_events(monkeypatch) -> None:
    """Preserve entry and successful-exit messages after removing Rich."""
    events = []
    monkeypatch.setattr(
        core_console,
        "print_step",
        lambda label, message: events.append(("step", label, message)),
    )
    monkeypatch.setattr(
        core_console,
        "print_done",
        lambda message: events.append(("done", message)),
    )

    with core_console.status_context("Synthetic operation"):
        pass

    assert events[0] == ("step", "RUN", "Synthetic operation")
    assert events[1][0] == "done"
    assert events[1][1].startswith("Synthetic operation  (")


def test_file_logging_uses_stdlib_handler(tmp_path) -> None:
    """File logging uses a replaceable standard-library FileHandler."""
    path = tmp_path / "run.log"
    core_logging.add_log_file(path, level="INFO")
    handler = core_logging._FILE_HANDLERS[path.resolve()]

    assert isinstance(handler, logging.FileHandler)
    assert handler.level == logging.INFO
