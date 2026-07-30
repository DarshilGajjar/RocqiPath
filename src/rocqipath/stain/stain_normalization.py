"""Compatibility façade for the refactored stain modules and CLI command."""

from __future__ import annotations

from typing import List, Optional

from rocqipath.cli.commands.stain import main as _command_main
from rocqipath.config import StainNormalizationConfig as StainNormalizationConfig
from rocqipath.stain.normalizers import (
    MacenkoNormalizer as MacenkoNormalizer,
    ReinhardNormalizer as ReinhardNormalizer,
    VahadaneNormalizer as VahadaneNormalizer,
    get_normalizer as get_normalizer,
    tissue_fraction as tissue_fraction,
)
from rocqipath.stain.pipeline import (
    run_stain_normalization_apply as run_stain_normalization_apply,
    run_stain_normalization_train as run_stain_normalization_train,
)

__all__ = [
    "StainNormalizationConfig",
    "ReinhardNormalizer",
    "MacenkoNormalizer",
    "VahadaneNormalizer",
    "get_normalizer",
    "run_stain_normalization_train",
    "run_stain_normalization_apply",
]


def main(argv: Optional[List[str]] = None) -> int:
    """Delegate the historical module invocation to the unified CLI command."""
    return _command_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
