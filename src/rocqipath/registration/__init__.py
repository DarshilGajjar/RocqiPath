"""Whole-slide alignment and registration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rocqipath.config import OrbConfig, ValisConfig

if TYPE_CHECKING:
    from .models import AlignedCaseResult
    from .pipeline import AlignmentConfig
    from .registrar import WSIRegistrar


__all__ = [
    "AlignmentConfig",
    "AlignedCaseResult",
    "OrbConfig",
    "ValisConfig",
    "WSIRegistrar",
    "run_alignment",
]


_PIPELINE_EXPORTS = {
    "AlignmentConfig",
    "AlignedCaseResult",
    "run_alignment",
}


def __getattr__(name: str):
    if name in _PIPELINE_EXPORTS:
        from . import pipeline

        value = getattr(pipeline, name)
        globals()[name] = value
        return value

    if name == "WSIRegistrar":
        try:
            from .registrar import WSIRegistrar
        except (ImportError, OSError) as exc:
            raise AttributeError(
                "WSIRegistrar is unavailable because registration "
                "dependencies could not be imported."
            ) from exc

        globals()[name] = WSIRegistrar
        return WSIRegistrar

    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))