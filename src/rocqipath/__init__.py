"""RocqiPath: whole-slide image processing for computational pathology.

Everything most users need is available from the top level::

    import rocqipath as rp

    regions = rp.extract_tissue("slides/", "results/", target_magnification=10)
    aligned = rp.align("pairs/", "results/", backend="orb")
    counts = rp.count_cells("cd8_slides/", "results/", label="CD8")

Every workflow is called the same way,
``rp.<workflow>(inputs, output_dir, *, config=None, **settings)``, and returns
a `Result` listing the files it produced. `list_workflows`
shows them all. Settings are fields of each workflow's config class
(``rp.AlignConfig``, ``rp.CountCellsConfig``, ...).

Nothing heavy is imported until it is used, so ``import rocqipath`` works
with no optional dependencies installed.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _distribution_version

from rocqipath._internal.lazy import lazy_exports as _lazy_exports

try:
    __version__ = _distribution_version("rocqipath")
except _PackageNotFoundError:
    __version__ = "0+unknown"

_WORKFLOWS = (
    "align",
    "compare",
    "count_cells",
    "extract_patches",
    "extract_tissue",
    "extract_tma",
    "normalize_stain",
    "overlay_markers",
    "train_stain_normalizer",
)
_ERRORS = (
    "ConfigurationError",
    "DependencyError",
    "ExtractionError",
    "RegistrationError",
    "RegistrationQualityError",
    "RocqiPathError",
    "SlideNotFoundError",
    "UnsupportedFormatError",
)

__getattr__, __dir__, _lazy_all = _lazy_exports(
    __name__,
    {
        **{name: "rocqipath.api" for name in _WORKFLOWS},
        **{name: "rocqipath.errors" for name in _ERRORS},
        "Item": "rocqipath.registry",
        "Result": "rocqipath.registry",
        "list_workflows": "rocqipath.registry",
        "run": "rocqipath.registry",
        "open_slide": "rocqipath.io.slide",
        "set_log_level": "rocqipath._internal.logging",
        "AlignConfig": "rocqipath.alignment.config",
        "OrbOptions": "rocqipath.alignment.config",
        "ValisOptions": "rocqipath.alignment.config",
        "CountCellsConfig": "rocqipath.counting.config",
        "ExtractPatchesConfig": "rocqipath.extraction.config",
        "ExtractTMAConfig": "rocqipath.extraction.config",
        "ExtractTissueConfig": "rocqipath.extraction.config",
        "StainConfig": "rocqipath.stain.config",
        "CompareConfig": "rocqipath.viz.config",
        "MarkerProfile": "rocqipath.viz.config",
        "OverlayCombo": "rocqipath.viz.config",
        "OverlayConfig": "rocqipath.viz.config",
    },
)

__all__ = ["__version__", *_lazy_all]
