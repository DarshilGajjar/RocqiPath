"""Settings for the ``count_cells`` workflow."""

from __future__ import annotations

from dataclasses import dataclass

from rocqipath.io.magnification import DEFAULT_TARGET_MAGNIFICATION
from rocqipath._internal.validation import (
    require,
    validate_fraction,
    validate_positive,
)

from rocqipath._internal.base_config import BaseConfig


@dataclass
class CountCellsConfig(BaseConfig):
    """Settings for `rocqipath.count_cells`.

    Counts brown (DAB-positive) cells on IHC slides patch by patch: an HSV
    color gate finds brown pixels and a per-patch Otsu threshold separates
    cells from lighter background staining.

    Parameters
    ----------
    label : str
        Marker name stored in the results, e.g. ``"CD8"``.
    patch_size : int
        Patch edge in target-magnification pixels.
    tissue_threshold : float
        Inclusive minimum tissue fraction per patch.
    target_magnification : float
        Physical objective magnification for analysis coordinates.
    source_magnification, paired_source_magnification : float, optional
        Objective fallbacks for single and paired slides.
    min_cell_area : int
        Minimum connected-component area in target-grid pixels squared.
    max_cell_area : int, optional
        Maximum component area in target-grid pixels squared.
    save_plots : bool
        When comparing two slides, save per-patch comparison figures.
    max_plots : int
        Maximum number of comparison figures saved per slide pair.
    dpi : int
        Resolution of comparison figures.
    """

    label: str = "Cell"

    patch_size: int = 512
    tissue_threshold: float = 0.10
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    source_magnification: float | None = None
    paired_source_magnification: float | None = None
    min_cell_area: int = 50
    max_cell_area: int | None = None
    save_plots: bool = True
    max_plots: int = 10
    dpi: int = 150

    def __post_init__(self) -> None:
        """Normalize scalar input and preserve existing validation."""
        self.patch_size = int(self.patch_size)
        self.tissue_threshold = float(self.tissue_threshold)
        self.target_magnification = float(self.target_magnification)
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


__all__ = ["CountCellsConfig"]
