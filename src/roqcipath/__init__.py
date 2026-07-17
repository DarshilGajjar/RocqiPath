"""RocqiPath: modular whole-slide image processing for computational pathology."""

from __future__ import annotations

from .exceptions import *  # noqa: F403
from .magnification import DEFAULT_TARGET_MAGNIFICATION, MagnificationPlan
from .output import OutputLayout

__version__ = "1.1.0"

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
