"""Visual quality-control and publication figure helpers."""

from .ihc_overlay import IHCOverlayConfig, MarkerProfile, OverlayCombo, process_ihc_overlay
from .visualization import plot_selector_map, view_pairs

__all__ = [
    "IHCOverlayConfig", "MarkerProfile", "OverlayCombo", "plot_selector_map",
    "process_ihc_overlay", "view_pairs",
]
