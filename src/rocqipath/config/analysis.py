"""Typed quantitative-analysis configurations."""

from __future__ import annotations

import os
from dataclasses import dataclass

from rocqipath.core.magnification import DEFAULT_TARGET_MAGNIFICATION
from rocqipath.utils.validation import (
    require,
    validate_fraction,
    validate_positive,
)

from .base import BaseConfig


@dataclass
class CellCountingConfig(BaseConfig):
    """Configure DAB-positive whole-slide cell counting.

    Parameters
    ----------
    patch_size : int
        Patch edge in target-magnification pixels.
    tissue_threshold : float
        Inclusive minimum tissue fraction per patch.
    target_magnification : float
        Physical objective magnification for analysis coordinates.
    source_magnification, paired_source_magnification : float, optional
        Objective fallbacks for single and paired slides.
    output_dir : str
        Root for JSON, Excel, and figure outputs.
    min_cell_area : int
        Minimum connected-component area in target-grid pixels squared.
    max_cell_area : int, optional
        Maximum component area in target-grid pixels squared.
    """

    patch_size: int = 512
    tissue_threshold: float = 0.10
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    source_magnification: float | None = None
    paired_source_magnification: float | None = None
    output_dir: str = "./cell_count_output"
    min_cell_area: int = 50
    max_cell_area: int | None = None

    def __post_init__(self) -> None:
        """Normalize scalar input and preserve existing validation."""
        self.patch_size = int(self.patch_size)
        self.tissue_threshold = float(self.tissue_threshold)
        self.target_magnification = float(self.target_magnification)
        self.output_dir = os.path.abspath(self.output_dir)
        self.min_cell_area = int(self.min_cell_area)
        self.max_cell_area = (
            int(self.max_cell_area) if self.max_cell_area not in (None, "", 0) else None
        )
        validate_positive(self.patch_size, name="patch_size")
        validate_positive(
            self.target_magnification,
            name="target_magnification",
        )
        validate_fraction(self.tissue_threshold, name="tissue_threshold")
        validate_positive(self.min_cell_area, name="min_cell_area")
        require(
            self.max_cell_area is None or self.max_cell_area >= self.min_cell_area,
            "max_cell_area must be >= min_cell_area",
        )


__all__ = ["CellCountingConfig"]
