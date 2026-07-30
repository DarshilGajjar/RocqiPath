"""Typed marker and IHC-overlay visualization configurations."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.utils.validation import require

from .base import BaseConfig

SUPPORTED_MARKER_METHODS = frozenset({"hsv"})
BASE_RENDER_MODES = frozenset({"mask", "original"})
PLOT_MODES = frozenset({"grid", "composite", "both"})


@dataclass
class MarkerProfile(BaseConfig):
    """Configure detection and rendering for one IHC marker.

    Parameters
    ----------
    color : tuple of int
        RGB overlay color, with each channel in ``[0, 255]``.
    label : str
        Human-readable figure label.
    method : {"hsv"}
        Marker detection method.
    hue_range : tuple of int
        Inclusive OpenCV hue bounds in ``[0, 179]``.
    sat_min : int
        Inclusive OpenCV saturation floor in ``[0, 255]``.
    """

    color: Tuple[int, int, int]
    method: str = "hsv"
    label: Optional[str] = None
    hue_range: Tuple[int, int] = (5, 20)
    sat_min: int = 30
    value_threshold: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate marker detection and color parameters."""
        require(
            self.method in SUPPORTED_MARKER_METHODS,
            f"MarkerProfile.method must be one of "
            f"{sorted(SUPPORTED_MARKER_METHODS)}; got {self.method!r}",
            exception_type=ConfigurationError,
        )
        require(
            len(self.color) == 3 and all(0 <= channel <= 255 for channel in self.color),
            f"color must be an (R, G, B) tuple with each value in [0, 255]; got {self.color}",
            exception_type=ConfigurationError,
        )
        low, high = self.hue_range
        require(
            0 <= low <= high <= 180,
            "hue_range must satisfy 0 <= low <= high <= 180 (OpenCV hue "
            f"convention); got {self.hue_range}",
            exception_type=ConfigurationError,
        )
        require(
            0 <= self.sat_min <= 255,
            f"sat_min must be in [0, 255]; got {self.sat_min}",
            exception_type=ConfigurationError,
        )


@dataclass
class OverlayCombo(BaseConfig):
    """Configure one base marker and its ordered overlay layers.

    Parameters
    ----------
    base : str
        Marker key used for the base image or mask.
    overlays : list of str
        Marker keys painted in order; later markers overwrite earlier ones.
    """

    base: str
    overlays: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Require at least one overlay marker."""
        require(
            bool(self.overlays),
            "OverlayCombo.overlays must be a non-empty list of marker keys.",
            exception_type=ConfigurationError,
        )


@dataclass
class IHCOverlayConfig(BaseConfig):
    """Configure multi-marker IHC overlay compositing and figure output.

    Parameters
    ----------
    markers : dict
        Marker keys mapped to :class:`MarkerProfile` values.
    combinations : list of OverlayCombo
        Base/overlay figures to generate.
    base_marker : str, optional
        Default base key used when combinations are synthesized.
    base_render_mode : {"mask", "original"}
        Render the base as its binary color mask or original RGB patch.
    plot_mode : {"composite", "grid", "both"}
        Figure types to save.
    save_dir : str
        Output root.
    patches_per_case : int
        Random patch cap; zero processes every shared filename.
    max_workers : int
        Case-level thread count.
    dpi : int
        Figure resolution in dots per inch.
    show_plot : bool
        Display figures interactively.
    skip_existing : bool
        Skip requested figures already present.
    """

    markers: Dict[str, MarkerProfile]
    combinations: List[OverlayCombo]
    base_marker: str
    base_render_mode: str = "mask"
    plot_mode: str = "composite"
    show_plot: bool = False
    save_dir: str = "./binary_plots"
    dpi: int = 300
    patches_per_case: int = 0
    skip_existing: bool = True
    max_workers: int = 1

    def __post_init__(self) -> None:
        """Validate marker references, output modes, and execution limits."""
        require(
            bool(self.markers),
            "markers must be a non-empty dict of MarkerProfile.",
            exception_type=ConfigurationError,
        )
        require(
            self.base_marker in self.markers,
            f"base_marker {self.base_marker!r} not found in markers: {sorted(self.markers)}",
            exception_type=ConfigurationError,
        )
        require(
            self.base_render_mode in BASE_RENDER_MODES,
            f"base_render_mode must be one of {sorted(BASE_RENDER_MODES)}; "
            f"got {self.base_render_mode!r}",
            exception_type=ConfigurationError,
        )
        require(
            self.plot_mode in PLOT_MODES,
            f"plot_mode must be one of {sorted(PLOT_MODES)}; got {self.plot_mode!r}",
            exception_type=ConfigurationError,
        )
        require(
            self.dpi > 0,
            f"dpi must be > 0; got {self.dpi}",
            exception_type=ConfigurationError,
        )
        require(
            self.patches_per_case >= 0,
            f"patches_per_case must be >= 0; got {self.patches_per_case}",
            exception_type=ConfigurationError,
        )
        require(
            self.max_workers >= 1,
            f"max_workers must be >= 1; got {self.max_workers}",
            exception_type=ConfigurationError,
        )
        require(
            bool(self.combinations),
            "combinations must be a non-empty list of OverlayCombo.",
            exception_type=ConfigurationError,
        )
        for combo in self.combinations:
            require(
                combo.base in self.markers,
                f"OverlayCombo.base {combo.base!r} not found in markers: {sorted(self.markers)}",
                exception_type=ConfigurationError,
            )
            for overlay in combo.overlays:
                require(
                    overlay in self.markers,
                    f"OverlayCombo overlay {overlay!r} not found in markers: "
                    f"{sorted(self.markers)}",
                    exception_type=ConfigurationError,
                )
        for key, profile in self.markers.items():
            if not profile.label:
                profile.label = key
        os.makedirs(self.save_dir, exist_ok=True)

    @classmethod
    def from_dict(
        cls,
        values: Mapping[str, Any],
    ) -> "IHCOverlayConfig":
        """Deserialize nested marker profiles and overlay combinations."""
        payload = dict(values)
        payload["markers"] = {
            key: (value if isinstance(value, MarkerProfile) else MarkerProfile.from_dict(value))
            for key, value in payload["markers"].items()
        }
        payload["combinations"] = [
            value if isinstance(value, OverlayCombo) else OverlayCombo.from_dict(value)
            for value in payload["combinations"]
        ]
        return cls(**payload)


__all__ = ["IHCOverlayConfig", "MarkerProfile", "OverlayCombo"]
