"""Shared setup and magnification primitives for extraction pipelines."""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

from rocqipath.core.magnification import objective_magnification_from_properties
from rocqipath.utils.vips import vips_properties as _vips_properties

for _n in ("pyvips", "VIPS", "PIL", "PIL.Image", "PIL.TiffImagePlugin", "matplotlib", "openslide"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)
SUPPORTED_EXTENSIONS: frozenset = frozenset({".tif", ".tiff", ".svs"})


def _resolve_vips_magnification(img: Any, fallback: Optional[float]) -> Tuple[float, str]:
    """Resolve a pyvips image's objective magnification and metadata source."""
    return objective_magnification_from_properties(_vips_properties(img), fallback=fallback)
