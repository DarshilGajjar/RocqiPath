"""Compatibility façade for :mod:`rocqipath.registration.pipeline`."""

from rocqipath.registration.models import (
    AlignedCaseResult as AlignedCaseResult,
    CaseContext as CaseContext,
)
from rocqipath.registration.pipeline import *  # noqa: F401,F403
from rocqipath.registration.pipeline import (
    DEFAULT_FILENAME_PATTERN as DEFAULT_FILENAME_PATTERN,
    DEFAULT_MOVING_NAME as DEFAULT_MOVING_NAME,
    DEFAULT_REFERENCE_NAME as DEFAULT_REFERENCE_NAME,
    WSI_PROCESSING_AVAILABLE as WSI_PROCESSING_AVAILABLE,
    is_wsi_file as is_wsi_file,
)
from rocqipath.registration.quality import (
    _read_hq_center_crop as _read_hq_center_crop,
    qc_center_patch_side_by_side as qc_center_patch_side_by_side,
)
