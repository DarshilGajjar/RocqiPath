"""Typed stain-normalization workflow configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.utils.validation import require, validate_fraction

from .base import BaseConfig

NORMALIZER_TYPES = frozenset({"reinhard", "macenko", "vahadane"})


@dataclass
class StainNormalizationConfig(BaseConfig):
    """Configure stain-normalizer training and application.

    Parameters
    ----------
    n_type : {"reinhard", "macenko", "vahadane"}
        Normalization algorithm.
    stains : list of str
        Path tokens used to filter input patches.
    fit_min_tissue : float
        Inclusive minimum optical-density tissue fraction in ``[0, 1]``.
    max_train_patches : int
        Mosaic patch cap for Macenko and Vahadane fitting.
    resume : bool
        Skip normalized outputs that already exist.
    weights_path : str, optional
        Explicit ``.npz`` archive path.
    """

    n_type: str = "macenko"
    stains: List[str] = field(default_factory=lambda: ["he"])
    fit_min_tissue: float = 0.1
    max_train_patches: int = 1000
    resume: bool = False
    weights_path: Optional[str] = None

    def __post_init__(self) -> None:
        """Normalize names and preserve historical validation messages."""
        require(
            self.n_type.lower() in NORMALIZER_TYPES,
            f"n_type must be one of {sorted(NORMALIZER_TYPES)}; got '{self.n_type}'",
            exception_type=ConfigurationError,
        )
        self.n_type = self.n_type.lower()
        validate_fraction(
            self.fit_min_tissue,
            name="fit_min_tissue",
            message=f"fit_min_tissue must be in [0, 1]; got {self.fit_min_tissue}",
            exception_type=ConfigurationError,
        )
        require(
            self.max_train_patches >= 1,
            f"max_train_patches must be >= 1; got {self.max_train_patches}",
            exception_type=ConfigurationError,
        )
        if isinstance(self.stains, str):
            self.stains = [stain.strip() for stain in self.stains.split(",") if stain.strip()]


__all__ = ["NORMALIZER_TYPES", "StainNormalizationConfig"]
