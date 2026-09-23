"""Tissue-region, TMA-core and paired-patch extraction.

Most users call `rocqipath.extract_tissue`, `rocqipath.extract_tma`
and `rocqipath.extract_patches`. This package also exposes the building
blocks those workflows use.
"""

from rocqipath._internal.lazy import lazy_exports

__getattr__, __dir__, __all__ = lazy_exports(
    __name__,
    {
        "ExtractPatchesConfig": ".config",
        "ExtractTMAConfig": ".config",
        "ExtractTissueConfig": ".config",
        "ReversiblePatchExtractor": ".reversible",
        "extract_patches_single": ".patch_single",
        "extract_tissue_regions": ".regions",
    },
)
