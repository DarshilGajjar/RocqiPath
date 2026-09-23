"""Typed marker and IHC-overlay visualization configurations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from rocqipath.errors import ConfigurationError
from rocqipath._internal.validation import require

from rocqipath._internal.base_config import ADVANCED, BaseConfig

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
    hue_range : tuple of int
        Inclusive OpenCV hue bounds in ``[0, 179]``.
    sat_min : int
        Inclusive OpenCV saturation floor in ``[0, 255]``.
    """

    color: Tuple[int, int, int]
    label: Optional[str] = None
    hue_range: Tuple[int, int] = (5, 20)
    sat_min: int = 30

    def __post_init__(self) -> None:
        """Validate marker detection and color parameters."""
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
class OverlayConfig(BaseConfig):
    """Settings for :func:`rocqipath.overlay_markers`.

    Each case folder holds one subfolder of patches per marker, with the
    same patch filenames in each. Every marker is converted to a colored
    mask and layered over a base marker to show co-localization.

    ``markers`` and ``combinations`` have no defaults because they depend
    on your stains; see the example below.

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

    Examples
    --------
    >>> cfg = OverlayConfig(
    ...     markers={"he": MarkerProfile(color=(0, 0, 255)), "cd8": MarkerProfile(color=(255, 0, 0))},
    ...     combinations=[OverlayCombo(base="he", overlays=["cd8"])],
    ...     base_marker="he",
    ... )
    """

    markers: Dict[str, MarkerProfile]
    combinations: List[OverlayCombo]
    base_marker: str
    base_render_mode: Literal["mask", "original"] = "mask"
    plot_mode: Literal["composite", "grid", "both"] = "composite"
    show_plot: bool = False
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

    @classmethod
    def from_dict(
        cls,
        values: Mapping[str, Any],
    ) -> "OverlayConfig":
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


#: Named zoom levels mapped to square crop edges in source pixels.
ZOOM_EDGES = {"40x": 512, "20x": 1000, "10x": 2000, "5x": 4000}
#: Named anchors for fixed-position comparison crops.
COMPARE_REGIONS = ("center", "top_left", "top_right", "bottom_left", "bottom_right")


@dataclass
class CompareConfig(BaseConfig):
    """Settings for :func:`rocqipath.compare`.

    Builds publication figures showing an H&E slide, its ground-truth IHC
    and a predicted IHC side by side: one full view plus zoomed crops at
    fixed anchors and, optionally, random tissue regions.

    Parameters
    ----------
    title_reference : str
        Title of the H&E panel.
    title_truth : str
        Title of the ground-truth IHC panel.
    title_prediction : str
        Title of the predicted IHC panel.
    dpi : int
        Figure resolution in dots per inch.
    regions : list of str
        Fixed crop anchors: any of ``center``, ``top_left``, ``top_right``,
        ``bottom_left``, ``bottom_right``.
    zooms : list of str
        Crop sizes, as names (``40x`` = 512 px, ``20x`` = 1000 px,
        ``10x`` = 2000 px, ``5x`` = 4000 px) or ``label:edge`` pairs such as
        ``detail:256``.
    random_rois : int
        Random tissue crops per zoom level, 0 to 10. Zero disables them.
    roi_seed : int
        Seed for choosing random crops; saved next to the figures.
    scale_bars : bool
        Draw physically calibrated scale bars on crops.
    mpp : float, optional
        Micrometres per pixel for scale bars; a per-zoom table is used
        when omitted.
    figure_name : str
        File name of the full-view figure. Crop names derive from it.
    """

    title_reference: str = "H&E"
    title_truth: str = "Ground Truth IHC"
    title_prediction: str = "Predicted IHC"
    dpi: int = 600
    regions: List[str] = field(default_factory=lambda: list(COMPARE_REGIONS))
    zooms: List[str] = field(default_factory=lambda: list(ZOOM_EDGES))
    random_rois: int = 0
    roi_seed: int = field(default=42, metadata=ADVANCED)
    scale_bars: bool = False
    mpp: Optional[float] = field(default=None, metadata=ADVANCED)
    figure_name: str = field(default="comparison.png", metadata=ADVANCED)

    def __post_init__(self) -> None:
        """Validate anchors, zoom names and the random-crop count."""
        unknown = [region for region in self.regions if region not in COMPARE_REGIONS]
        require(not unknown, f"Unknown region(s) {unknown}; choose from {list(COMPARE_REGIONS)}")
        self.zoom_sizes()
        require(0 <= self.random_rois <= 10, "random_rois must be between 0 and 10")
        require(self.dpi > 0, f"dpi must be > 0; got {self.dpi}")

    def zoom_sizes(self) -> List[Tuple[str, int]]:
        """Return ``(label, edge)`` pairs for :attr:`zooms`."""
        sizes = []
        for zoom in self.zooms:
            label, _, edge = str(zoom).partition(":")
            if edge:
                require(edge.isdigit() and int(edge) > 0, f"Invalid zoom {zoom!r}")
                sizes.append((label, int(edge)))
            else:
                require(label in ZOOM_EDGES, f"Unknown zoom {zoom!r}; use {list(ZOOM_EDGES)} or label:edge")
                sizes.append((label, ZOOM_EDGES[label]))
        return sizes


__all__ = ["COMPARE_REGIONS", "CompareConfig", "MarkerProfile", "OverlayCombo", "OverlayConfig", "ZOOM_EDGES"]
