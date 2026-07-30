"""Compatibility façade for :mod:`rocqipath.extraction.tissue`."""

from .tissue import *  # noqa: F401,F403
from .tissue import (
    _detect_regions as _detect_regions,
    _load_thumbnail as _load_thumbnail,
    extract_tissue_regions as extract_tissue_regions,
    run_tissue_pipeline as run_tissue_pipeline,
)
from rocqipath.config import TissueExtractionConfig as TissueExtractionConfig
