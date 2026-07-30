"""Deprecated façade for utility workflows moved to feature packages."""

from __future__ import annotations

import warnings

from rocqipath.extraction.patches import extract_patches_single
from rocqipath.visualization.grids import (
    export_grid_map,
    export_paired_grid_maps,
    generate_single_grid_map_for_slide,
    save_paired_grid_map_figure,
)
from rocqipath.visualization.pairs import visualize_patch_pairs
from rocqipath.visualization.thumbnails import export_wsi_thumbnails

warnings.warn(
    "rocqipath.api is deprecated; import helpers from rocqipath.extraction.patches "
    "or rocqipath.visualization instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "export_grid_map",
    "export_paired_grid_maps",
    "export_wsi_thumbnails",
    "extract_patches_single",
    "generate_single_grid_map_for_slide",
    "save_paired_grid_map_figure",
    "visualize_patch_pairs",
]
