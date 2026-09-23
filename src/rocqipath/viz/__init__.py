"""Quality-control and publication figures.

Most users call :func:`rocqipath.compare` and :func:`rocqipath.overlay_markers`.
The plotting helpers here draw grid maps, patch pairs and thumbnails.
"""

from rocqipath._internal.lazy import lazy_exports

__getattr__, __dir__, __all__ = lazy_exports(
    __name__,
    {
        "CompareConfig": ".config",
        "MarkerProfile": ".config",
        "OverlayCombo": ".config",
        "OverlayConfig": ".config",
        "export_grid_map": ".grids",
        "export_paired_grid_maps": ".grids",
        "export_wsi_thumbnails": ".thumbnails",
        "plot_selector_map": ".grids",
        "view_pairs": ".pairs",
    },
)
