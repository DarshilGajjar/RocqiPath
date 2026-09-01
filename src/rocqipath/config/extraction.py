"""Typed configurations for tissue, TMA, and paired-patch extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

from rocqipath.core.magnification import DEFAULT_TARGET_MAGNIFICATION
from rocqipath.utils.validation import (
    require,
    validate_fraction,
    validate_positive,
)

from .base import BaseConfig

DEFAULT_REFERENCE_FILENAME_PATTERN = (
    r"^(?P<sample_id>.+?)"
    r"(?:_he|__he__s\d+)"
    r"\.(?:tif|tiff|svs|ndpi|mrxs)$"
)


@dataclass
class BaseExtractionConfig(BaseConfig):
    """Configure fields shared by tissue and TMA region extraction.

    Parameters
    ----------
    target_magnification : float
        Physical objective magnification of saved regions.
    detection_magnification : float
        Physical objective magnification used for contour detection.
    source_magnification : float, optional
        Objective fallback when slide metadata is absent.
    preview_scale : float
        Preview dimensions as a fraction of extracted-region dimensions.
    min_area_fraction : float
        Minimum contour area as a fraction of the detection thumbnail.
    tif_tile, tif_pyramid : bool
        Enable tiled and pyramidal TIFF output.
    tif_compression : str
        libvips TIFF compression name.
    tif_quality : int
        TIFF encoder quality in ``[1, 100]``.
    skip_existing : bool
        Skip regions whose TIFF, preview, and manifest all exist.
    """

    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    detection_magnification: float = 1.25
    source_magnification: Optional[float] = None
    preview_scale: float = 0.2
    min_area_fraction: float = 0.0005
    tif_tile: bool = True
    tif_pyramid: bool = True
    tif_compression: str = "lzw"
    tif_quality: int = 99
    skip_existing: bool = True
    detector: Literal["otsu", "semantic"] = "otsu"
    semantic_model: str = "fcn-tissue_mask"
    semantic_weights_path: Optional[str] = None
    semantic_device: Literal["auto", "cpu", "cuda"] = "auto"
    semantic_batch_size: int = 4
    semantic_num_workers: int = 0
    semantic_source_mpp: Optional[float] = None

    def __post_init__(self) -> None:
        """Preserve shared extraction validation and user-facing messages."""
        validate_fraction(
            self.min_area_fraction,
            name="min_area_fraction",
            message=f"min_area_fraction must be in [0, 1]; got {self.min_area_fraction}",
        )
        validate_positive(
            self.preview_scale,
            name="preview_scale",
            message=f"preview_scale must be > 0; got {self.preview_scale}",
        )
        require(
            1 <= self.tif_quality <= 100,
            f"tif_quality must be in [1, 100]; got {self.tif_quality}",
        )
        validate_positive(
            self.target_magnification,
            name="target_magnification",
        )
        validate_positive(
            self.detection_magnification,
            name="detection_magnification",
        )
        require(
            self.detection_magnification <= self.target_magnification,
            "detection_magnification cannot exceed target_magnification",
        )
        if self.source_magnification is not None:
            validate_positive(
                self.source_magnification,
                name="source_magnification",
                message="source_magnification must be > 0 when supplied",
            )
        require(
            self.detector in {"otsu", "semantic"},
            f"detector must be 'otsu' or 'semantic'; got {self.detector!r}",
        )
        require(bool(self.semantic_model.strip()), "semantic_model cannot be empty")
        require(
            self.semantic_device in {"auto", "cpu", "cuda"},
            "semantic_device must be 'auto', 'cpu', or 'cuda'",
        )
        require(
            self.semantic_batch_size >= 1,
            "semantic_batch_size must be >= 1",
        )
        require(
            self.semantic_num_workers >= 0,
            "semantic_num_workers must be >= 0",
        )
        if self.semantic_source_mpp is not None:
            validate_positive(
                self.semantic_source_mpp,
                name="semantic_source_mpp",
                message="semantic_source_mpp must be > 0 when supplied",
            )


@dataclass
class TissueExtractionConfig(BaseExtractionConfig):
    """Configure contiguous whole-slide tissue region extraction.

    This specialization uses the shared extraction fields with a larger
    default minimum area fraction and no circularity gate.
    """

    min_area_fraction: float = 0.005


@dataclass
class TMAExtractionConfig(BaseExtractionConfig):
    """Configure circular multi-region or TMA extraction.

    Parameters
    ----------
    only_circles : bool
        Apply the circularity gate.
    min_circularity : float
        Minimum dimensionless ``4πA/P²`` score in ``[0, 1]``.
    per_stain_detection : bool
        Detect regions independently on each stain.
    fallback_to_he : bool
        Reuse reference boxes when moving-stain region counts differ.
    box_scale : float
        Multiplicative expansion around each detected bounding box.
    ihc_enhance : bool
        Apply the historical CLAHE/DAB enhancement.
    clahe_clip_limit : float
        OpenCV CLAHE contrast limit.
    clahe_tile_size : tuple of int
        CLAHE tile dimensions in extracted-region pixels.
    """

    only_circles: bool = True
    min_circularity: float = 0.70
    per_stain_detection: bool = True
    fallback_to_he: bool = True
    box_scale: float = 1.0
    ihc_enhance: bool = True
    clahe_clip_limit: float = 3.0
    clahe_tile_size: Tuple[int, int] = field(default_factory=lambda: (8, 8))
    min_aspect_ratio: float = 0.90
    min_solidity: float = 0.95
    min_relative_area: float = 0.80
    max_relative_area: float = 1.20

    def __post_init__(self) -> None:
        """Validate TMA fields after the shared extraction fields."""
        super().__post_init__()
        validate_fraction(
            self.min_circularity,
            name="min_circularity",
            message=f"min_circularity must be in [0, 1]; got {self.min_circularity}",
        )
        validate_positive(
            self.box_scale,
            name="box_scale",
            message=f"box_scale must be > 0; got {self.box_scale}",
        )
        validate_positive(
            self.clahe_clip_limit,
            name="clahe_clip_limit",
            message=f"clahe_clip_limit must be > 0; got {self.clahe_clip_limit}",
        )
        validate_fraction(self.min_aspect_ratio, name="min_aspect_ratio")
        validate_fraction(self.min_solidity, name="min_solidity")
        validate_positive(self.min_relative_area, name="min_relative_area")
        validate_positive(self.max_relative_area, name="max_relative_area")
        require(
            self.min_relative_area <= self.max_relative_area,
            "min_relative_area cannot exceed max_relative_area",
        )


@dataclass
class PatchExtractionConfig(BaseConfig):
    """Configure generalized paired sliding-window patch extraction.

    Parameters
    ----------
    he_dir, aligned_dir, output_dir : str
        Reference input, aligned-target input, and output roots.
    biomarker_folders : list of str
        Marker subfolders to process.
    reference_pattern : str
        Filename regex with a named ``sample_id`` group.
    reference_name, moving_name : str
        Channel tokens used in metadata and output filenames.
    patch_size : int
        Square patch edge in target-magnification pixels.
    stride : int, optional
        Sliding step in target-magnification pixels; defaults to patch size.
    tissue_threshold : float
        Inclusive minimum tissue fraction in ``[0, 1]``.
    max_workers : int
        Case-level thread count.
    target_magnification : float
        Physical extraction objective magnification.
    reference_source_magnification, target_source_magnification : float, optional
        Objective fallbacks when metadata is absent.
    dimension_tolerance : float
        Maximum relative target-dimension mismatch.
    """

    he_dir: str
    aligned_dir: str
    output_dir: str
    biomarker_folders: List[str]
    reference_pattern: str = DEFAULT_REFERENCE_FILENAME_PATTERN
    reference_name: str = "he"
    moving_name: str = "ihc"
    patch_size: int = 512
    stride: Optional[int] = None
    tissue_threshold: float = 0.5
    max_workers: int = 1
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    reference_source_magnification: Optional[float] = None
    target_source_magnification: Optional[float] = None
    dimension_tolerance: float = 0.01

    def __post_init__(self) -> None:
        """Resolve stride and preserve all historical validation messages."""
        require(
            bool(self.biomarker_folders),
            "biomarker_folders must be a non-empty list.",
        )
        validate_positive(
            self.patch_size,
            name="patch_size",
            message=f"patch_size must be > 0; got {self.patch_size}",
        )
        if self.stride is None:
            self.stride = self.patch_size
        validate_positive(
            self.stride,
            name="stride",
            message=f"stride must be > 0; got {self.stride}",
        )
        validate_fraction(
            self.tissue_threshold,
            name="tissue_threshold",
            message=f"tissue_threshold must be in [0, 1]; got {self.tissue_threshold}",
        )
        require(
            self.max_workers >= 1,
            f"max_workers must be >= 1; got {self.max_workers}",
        )
        validate_positive(
            self.target_magnification,
            name="target_magnification",
        )
        for name, value in (
            (
                "reference_source_magnification",
                self.reference_source_magnification,
            ),
            (
                "target_source_magnification",
                self.target_source_magnification,
            ),
        ):
            if value is not None:
                validate_positive(
                    value,
                    name=name,
                    message=f"{name} must be > 0 when supplied",
                )
        validate_fraction(
            self.dimension_tolerance,
            name="dimension_tolerance",
        )
        try:
            compiled = re.compile(self.reference_pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"reference_pattern is not a valid regex: {exc}") from exc
        require(
            "sample_id" in compiled.groupindex,
            "reference_pattern must define named group 'sample_id'. "
            f"Pattern: {self.reference_pattern!r}",
        )


__all__ = [
    "BaseExtractionConfig",
    "DEFAULT_REFERENCE_FILENAME_PATTERN",
    "PatchExtractionConfig",
    "TMAExtractionConfig",
    "TissueExtractionConfig",
]
