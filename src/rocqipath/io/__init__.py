"""Slide reading, magnification, file discovery, naming and output layout.

Nothing is imported until a name is first used, so importing this package
needs no optional dependencies.
"""

from rocqipath._internal.lazy import lazy_exports

__getattr__, __dir__, __all__ = lazy_exports(
    __name__,
    {
        "DEFAULT_TARGET_MAGNIFICATION": ".magnification",
        "MagnificationPlan": ".magnification",
        "OutputLayout": ".output",
        "SlideReader": ".slide",
        "build_magnification_plan": ".magnification",
        "detect_wsi_format": ".discovery",
        "discover_matching_files": ".discovery",
        "discover_patch_pairs": ".discovery",
        "find_aligned_wsi": ".discovery",
        "find_hne_ihc_pairs_by_suffix": ".discovery",
        "is_wsi_file": ".discovery",
        "list_wsi_files": ".discovery",
        "natural_sort_key": ".naming",
        "objective_magnification_from_properties": ".magnification",
        "safe_name": ".output",
    },
)
