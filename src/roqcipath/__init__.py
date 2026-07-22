"""RocqiPath: modular whole-slide image processing for computational pathology."""

from __future__ import annotations

from importlib.metadata import version
__version__ = version("rocqipath")

from .exceptions import *  # noqa: F403
from .magnification import (
    DEFAULT_TARGET_MAGNIFICATION as DEFAULT_TARGET_MAGNIFICATION,
    MagnificationPlan as MagnificationPlan,
)
from .output import OutputLayout as OutputLayout

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
    from .registration import AlignmentConfig, ValisConfig, WSIRegistrar, run_alignment  # noqa: F401
except ImportError:
    pass

try:
    from .stain import StainNormalizationConfig  # noqa: F401
except ImportError:
    pass