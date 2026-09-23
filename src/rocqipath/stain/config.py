"""Settings for the ``train_stain_normalizer`` and ``normalize_stain`` workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal

from rocqipath.errors import ConfigurationError
from rocqipath._internal.validation import require, validate_fraction

from rocqipath._internal.base_config import ADVANCED, BaseConfig

NORMALIZER_TYPES = frozenset({"reinhard", "macenko", "vahadane"})


@dataclass
class StainConfig(BaseConfig):
    """Settings for :func:`rocqipath.train_stain_normalizer` and :func:`rocqipath.normalize_stain`.

    Training fits one normalizer to reference patches and saves its weights;
    normalizing applies saved weights to other images so their stain colors
    match the reference.

    Parameters
    ----------
    method : {"reinhard", "macenko", "vahadane"}
        Normalization algorithm. Reinhard matches color statistics and is
        fastest; Macenko and Vahadane estimate stain vectors and preserve
        structure better. All three need the ``stain`` extra (TIAToolbox).
    stains : list of str
        Only use images whose path contains one of these folder names,
        e.g. ``["he"]``. ``["all"]`` uses every image.
    fit_min_tissue : float
        Inclusive minimum optical-density tissue fraction in ``[0, 1]``.
    max_train_patches : int
        Mosaic patch cap for Macenko and Vahadane fitting.
    resume : bool
        Skip normalized outputs that already exist.
    """

    method: Literal["reinhard", "macenko", "vahadane"] = "macenko"
    stains: List[str] = field(default_factory=lambda: ["he"])
    fit_min_tissue: float = 0.1
    max_train_patches: int = field(default=1000, metadata=ADVANCED)
    resume: bool = False

    def __post_init__(self) -> None:
        """Normalize names and preserve historical validation messages."""
        require(
            self.method.lower() in NORMALIZER_TYPES,
            f"method must be one of {sorted(NORMALIZER_TYPES)}; got '{self.method}'",
            exception_type=ConfigurationError,
        )
        self.method = self.method.lower()
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


__all__ = ["NORMALIZER_TYPES", "StainConfig"]
