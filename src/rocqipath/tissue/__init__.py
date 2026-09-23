"""Tissue-detection primitives shared by extraction, counting and stain workflows.

Region detectors (:mod:`rocqipath.tissue.detection`, :mod:`rocqipath.tissue.semantic`)
need OpenCV or TIAToolbox and are imported from their modules directly.
"""

from .masks import (
    brightness_saturation_is_tissue,
    is_tissue,
    optical_density_max_channel,
    optical_density_otsu_mask,
    pil_brightness_saturation_fraction,
    pil_intensity_fraction,
    pil_is_tissue,
    tissue_fraction,
    tissue_mask,
)

__all__ = [
    "brightness_saturation_is_tissue",
    "is_tissue",
    "optical_density_max_channel",
    "optical_density_otsu_mask",
    "pil_brightness_saturation_fraction",
    "pil_intensity_fraction",
    "pil_is_tissue",
    "tissue_fraction",
    "tissue_mask",
]
