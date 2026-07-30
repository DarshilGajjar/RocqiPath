"""Compatibility façade for the refactored extraction engine internals."""

from .detection import _detect_regions as _detect_regions
from .detection import _load_thumbnail as _load_thumbnail
from .engine import SUPPORTED_EXTENSIONS as SUPPORTED_EXTENSIONS
from .engine import _resolve_vips_magnification as _resolve_vips_magnification
from .engine import configure_logging as configure_logging
