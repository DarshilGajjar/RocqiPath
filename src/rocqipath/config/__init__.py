"""Central typed configuration API for every RocqiPath feature package."""

from __future__ import annotations

import warnings
from typing import Any

from .analysis import CellCountingConfig
from .base import BaseConfig
from .extraction import (
    BaseExtractionConfig,
    CoreExtractionConfig,
    PatchExtractionConfig,
    TMAExtractionConfig,
    TissueExtractionConfig,
)
from .registration import (
    AlignmentConfig,
    OrbConfig,
    RegistrarDefaults,
    ValisConfig,
    default_config,
)
from .stain import StainNormalizationConfig
from .visualization import IHCOverlayConfig, MarkerProfile, OverlayCombo


def __getattr__(name: str) -> Any:
    """Compute the deprecated legacy registrar mapping on demand."""
    if name == "DEFAULT_CONFIG":
        warnings.warn(
            "rocqipath.config.DEFAULT_CONFIG is deprecated; use typed config dataclasses instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return default_config()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Include the compatibility mapping in interactive discovery."""
    return sorted([*globals(), "DEFAULT_CONFIG"])


__all__ = [
    "AlignmentConfig",
    "BaseConfig",
    "BaseExtractionConfig",
    "CellCountingConfig",
    "CoreExtractionConfig",
    "IHCOverlayConfig",
    "MarkerProfile",
    "OrbConfig",
    "OverlayCombo",
    "PatchExtractionConfig",
    "RegistrarDefaults",
    "StainNormalizationConfig",
    "TMAExtractionConfig",
    "TissueExtractionConfig",
    "ValisConfig",
    "default_config",
]
