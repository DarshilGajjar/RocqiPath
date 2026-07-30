"""Compatibility façade for the refactored patch-extraction modules."""

from rocqipath.config import PatchExtractionConfig as PatchExtractionConfig
from rocqipath.extraction.patch_pipeline import (
    _discover_reference_files as _discover_reference_files,
    _extract_case_patches as _extract_case_patches,
    _find_aligned_target as _find_aligned_target,
    _patch_is_tissue as _patch_is_tissue,
    run_patch_extraction as run_patch_extraction,
)
from rocqipath.extraction.reversible import ReversiblePatchExtractor as ReversiblePatchExtractor

__all__ = [
    "ReversiblePatchExtractor",
    "PatchExtractionConfig",
    "run_patch_extraction",
]
