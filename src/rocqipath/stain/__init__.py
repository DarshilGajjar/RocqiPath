"""Stain normalization: Reinhard, Macenko and Vahadane.

Most users call `rocqipath.train_stain_normalizer` and
`rocqipath.normalize_stain`. The normalizer classes fit and transform
individual images in memory.
"""

from rocqipath._internal.lazy import lazy_exports

__getattr__, __dir__, __all__ = lazy_exports(
    __name__,
    {
        "MacenkoNormalizer": ".normalizers",
        "ReinhardNormalizer": ".normalizers",
        "StainConfig": ".config",
        "VahadaneNormalizer": ".normalizers",
        "get_normalizer": ".normalizers",
    },
)
