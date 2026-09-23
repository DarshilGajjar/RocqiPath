"""Slide reading, magnification, file discovery, naming and output layout.

Imaging backends used by :class:`SlideReader` are loaded lazily, so importing
this package needs no optional dependencies.
"""

from .slide import (
    SlideReader,
)
from .magnification import (
    DEFAULT_TARGET_MAGNIFICATION,
    MagnificationPlan,
    build_magnification_plan,
    objective_magnification_from_properties,
)
from .output import (
    OutputLayout,
    safe_name,
)
from .discovery import (
    detect_wsi_format,
    discover_matching_files,
    discover_patch_pairs,
    find_aligned_wsi,
    find_hne_ihc_pairs_by_suffix,
    is_wsi_file,
    list_wsi_files,
)
from .naming import (
    natural_sort_key,
)

__all__ = [
    "DEFAULT_TARGET_MAGNIFICATION",
    "MagnificationPlan",
    "OutputLayout",
    "SlideReader",
    "build_magnification_plan",
    "detect_wsi_format",
    "discover_matching_files",
    "discover_patch_pairs",
    "find_aligned_wsi",
    "find_hne_ihc_pairs_by_suffix",
    "is_wsi_file",
    "list_wsi_files",
    "natural_sort_key",
    "objective_magnification_from_properties",
    "safe_name",
]
