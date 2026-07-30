"""Compatibility façade for :mod:`rocqipath.visualization.overlays`."""

from .overlay_figures import (
    _save_composite_figure as _save_composite_figure,
    _save_grid_figure as _save_grid_figure,
)
from .overlay_masks import (
    _build_composite as _build_composite,
    _marker_mask as _marker_mask,
)
from .overlays import *  # noqa: F401,F403
from .overlays import (
    _looks_like_case_dir as _looks_like_case_dir,
    _process_single_case as _process_single_case,
    _resolve_marker_dir as _resolve_marker_dir,
)
