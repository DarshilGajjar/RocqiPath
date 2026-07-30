"""Regression tests for shared-core moves and compatibility façades."""

from __future__ import annotations

import importlib
from contextlib import nullcontext

import rocqipath.logger as legacy_logger
from rocqipath.core.exceptions import WSIProcessingError as CoreWSIProcessingError
from rocqipath.core.logging import Timer, logger
from rocqipath.core.magnification import MagnificationPlan
from rocqipath.core.output import OutputLayout
from rocqipath.exceptions import WSIProcessingError
from rocqipath.logger import Timer as LegacyTimer
from rocqipath.logger import logger as legacy_loguru
from rocqipath.magnification import MagnificationPlan as LegacyMagnificationPlan
from rocqipath.output import OutputLayout as LegacyOutputLayout

core_console = importlib.import_module("rocqipath.core.console")


def test_flat_compatibility_modules_reexport_core_objects() -> None:
    """Keep pre-refactor infrastructure imports bound to canonical objects."""
    assert LegacyMagnificationPlan is MagnificationPlan
    assert LegacyOutputLayout is OutputLayout
    assert WSIProcessingError is CoreWSIProcessingError
    assert LegacyTimer is Timer
    assert legacy_loguru is logger
    assert "_demo" not in legacy_logger.__all__


def test_spinner_remains_a_context_manager(monkeypatch) -> None:
    """Preserve the generator helper's context-manager protocol after splitting."""
    sentinel = object()
    monkeypatch.setattr(
        core_console.console,
        "status",
        lambda *_args, **_kwargs: nullcontext(sentinel),
    )

    with core_console.spinner("synthetic") as status:
        assert status is sentinel


def test_status_context_preserves_success_events(monkeypatch) -> None:
    """Preserve entry and successful-exit messages after splitting the logger."""
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
