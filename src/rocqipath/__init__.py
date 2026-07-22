"""RocqiPath: modular whole-slide image processing for computational pathology."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _distribution_version

from .exceptions import *  # noqa: F403
from .magnification import (
    DEFAULT_TARGET_MAGNIFICATION as DEFAULT_TARGET_MAGNIFICATION,
    MagnificationPlan as MagnificationPlan,
)
from .output import OutputLayout as OutputLayout

try:
    __version__ = _distribution_version("rocqipath")
except _PackageNotFoundError:
    # Source-tree imports before installation have no distribution metadata.
    __version__ = "0+unknown"

# Optional pipelines are imported independently so a lightweight install can
# still use configuration and utility modules without every WSI backend.
try:
    from .extraction import (  # noqa: F401
        CoreExtractionConfig,
        PatchExtractionConfig,
        TissueExtractionConfig,
        run_core_extraction_pipeline,
        run_patch_extraction,
        run_tissue_pipeline,
    )
except ImportError:
    pass

try:
    from .registration import AlignmentConfig, run_alignment  # noqa: F401
except (ImportError, OSError):
    pass

try:
    from .registration.core import ValisConfig, WSIRegistrar  # noqa: F401
except (ImportError, OSError):
    pass

try:
    from .stain import StainNormalizationConfig  # noqa: F401
except ImportError:
    pass
