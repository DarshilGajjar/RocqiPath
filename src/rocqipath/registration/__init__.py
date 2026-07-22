"""Whole-slide alignment and registration."""

from .alignment import AlignmentConfig, AlignedCaseResult, run_alignment

__all__ = ["AlignmentConfig", "AlignedCaseResult", "run_alignment"]

try:
    from .core import ValisConfig as ValisConfig
    from .core import WSIRegistrar as WSIRegistrar
except (ImportError, OSError):
    pass
else:
    __all__.extend(["ValisConfig", "WSIRegistrar"])
