"""Whole-slide alignment and registration."""

from rocqipath.config import OrbConfig, ValisConfig

from .pipeline import AlignmentConfig, AlignedCaseResult, run_alignment

__all__ = [
    "AlignmentConfig",
    "AlignedCaseResult",
    "OrbConfig",
    "ValisConfig",
    "run_alignment",
]

try:
    from .registrar import WSIRegistrar as WSIRegistrar
except (ImportError, OSError):
    pass
else:
    __all__.append("WSIRegistrar")
