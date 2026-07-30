"""Compatibility façade for :mod:`rocqipath.visualization.comparison`."""

from __future__ import annotations

from .comparison import *  # noqa: F401,F403
from .comparison import (
    _add_scale_bar as _add_scale_bar,
    _build_banner as _build_banner,
    _region_bbox as _region_bbox,
    _tissue_fraction as _tissue_fraction,
    configure_logging as configure_logging,
    main,
)
from .figure_helpers import (
    _draw_roi_rectangles as _draw_roi_rectangles,
    _save_annotated_full_view as _save_annotated_full_view,
    _save_plot as _save_plot,
)
from .roi import (
    _is_tissue as _is_tissue,
    _load_or_create_roi_sidecar as _load_or_create_roi_sidecar,
    _random_roi_bbox as _random_roi_bbox,
    _score_crop as _score_crop,
)

if __name__ == "__main__":  # pragma: no cover - exercised through CLI smoke tests
    main()
