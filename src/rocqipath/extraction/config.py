"""Settings for the ``extract_tissue``, ``extract_tma`` and ``extract_patches`` workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

from rocqipath.io.magnification import DEFAULT_TARGET_MAGNIFICATION
from rocqipath._internal.validation import (
    require,
    validate_fraction,
    validate_positive,
)

from rocqipath._internal.base_config import ADVANCED, LOCAL_ONLY, BaseConfig

DEFAULT_REFERENCE_FILENAME_PATTERN = (
    r"^(?P<sample_id>.+?)"
    r"(?:_he|__he__s\d+)"
    r"\.(?:tif|tiff|svs|ndpi|mrxs)$"
)


@dataclass
class _RegionExtractionConfig(BaseConfig):
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
    detector : {"otsu", "semantic"}
        Tissue detector. ``"otsu"`` thresholds a low-magnification
        thumbnail and needs no model. ``"semantic"`` runs a TIAToolbox
        tissue-segmentation model (install the ``semantic`` extra).
    semantic_model : str
        TIAToolbox pretrained model name used when ``detector="semantic"``.
    semantic_weights_path : str, optional
        Local weights file overriding the pretrained download.
    semantic_device : {"auto", "cpu", "cuda"}
        Inference device; ``"auto"`` uses CUDA when available.
    semantic_batch_size : int
        Tiles per inference batch.
    semantic_num_workers : int
        Data-loader worker processes for inference.
    semantic_source_mpp : float, optional
        Microns-per-pixel fallback when the slide has no MPP metadata.
    """

    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    detection_magnification: float = 1.25
    source_magnification: Optional[float] = None
    preview_scale: float = field(default=0.2, metadata=ADVANCED)
    min_area_fraction: float = 0.0005
    tif_tile: bool = field(default=True, metadata=ADVANCED)
    tif_pyramid: bool = field(default=True, metadata=ADVANCED)
    tif_compression: str = field(default="lzw", metadata=ADVANCED)
    tif_quality: int = field(default=99, metadata=ADVANCED)
    skip_existing: bool = True
    detector: Literal["otsu", "semantic"] = "otsu"
    semantic_model: str = field(default="fcn-tissue_mask", metadata=ADVANCED)
    semantic_weights_path: Optional[str] = field(default=None, metadata=LOCAL_ONLY)
    semantic_device: Literal["auto", "cpu", "cuda"] = field(default="auto", metadata=ADVANCED)
    semantic_batch_size: int = field(default=4, metadata=ADVANCED)
    semantic_num_workers: int = field(default=0, metadata=ADVANCED)
    semantic_source_mpp: Optional[float] = field(default=None, metadata=ADVANCED)

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
class ExtractTissueConfig(_RegionExtractionConfig):
    """Settings for :func:`rocqipath.extract_tissue`.

    Detects separate pieces of tissue on each whole-slide image and saves
    each one as its own pyramidal TIFF with a preview and a manifest. This
    specialization uses the shared extraction fields with a larger default
    minimum area fraction and no circularity gate.

    Parameters
    ----------
    min_area_fraction : float
        Minimum contour area as a fraction of the detection thumbnail.
        Smaller specks are ignored. Default ``0.005``.

    Examples
    --------
    >>> ExtractTissueConfig(target_magnification=10.0, source_magnification=40.0)  # doctest: +ELLIPSIS
    ExtractTissueConfig(target_magnification=10.0, ...)
    """

    min_area_fraction: float = 0.005


@dataclass
class ExtractTMAConfig(_RegionExtractionConfig):
    """Settings for :func:`rocqipath.extract_tma`.

    Detects round tissue-microarray cores on each H&E slide and cuts the
    same cores out of every matching IHC slide of that block.

    Parameters
    ----------
    stains : list of str
        Stains to extract, matched against filenames (e.g. ``["HE", "CD8"]``).
        ``["all"]`` extracts every recognized stain.
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
    min_aspect_ratio : float
        Minimum short/long side ratio of a core's bounding box in ``[0, 1]``.
    min_solidity : float
        Minimum contour area divided by convex-hull area in ``[0, 1]``.
    min_relative_area, max_relative_area : float
        Accepted core area relative to the median core area of the block.
    """

    stains: List[str] = field(default_factory=lambda: ["all"])
    only_circles: bool = True
    min_circularity: float = 0.70
    per_stain_detection: bool = True
    fallback_to_he: bool = True
    box_scale: float = 1.0
    ihc_enhance: bool = True
    clahe_clip_limit: float = field(default=3.0, metadata=ADVANCED)
    clahe_tile_size: Tuple[int, int] = field(default_factory=lambda: (8, 8), metadata=ADVANCED)
    min_aspect_ratio: float = field(default=0.90, metadata=ADVANCED)
    min_solidity: float = field(default=0.95, metadata=ADVANCED)
    min_relative_area: float = field(default=0.80, metadata=ADVANCED)
    max_relative_area: float = field(default=1.20, metadata=ADVANCED)

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
class ExtractPatchesConfig(BaseConfig):
    """Settings for :func:`rocqipath.extract_patches`.

    Walks a sliding window over each reference slide and its aligned
    counterpart, saving matching patch pairs that contain enough tissue.

    Parameters
    ----------
    biomarker_folders : list of str
        Marker subfolders of the aligned input to process. Empty (the
        default) processes every subfolder.
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

    biomarker_folders: List[str] = field(default_factory=list)
    reference_pattern: str = field(default=DEFAULT_REFERENCE_FILENAME_PATTERN, metadata=ADVANCED)
    reference_name: str = "he"
    moving_name: str = "ihc"
    patch_size: int = 512
    stride: Optional[int] = None
    tissue_threshold: float = 0.5
    max_workers: int = 1
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    reference_source_magnification: Optional[float] = None
    target_source_magnification: Optional[float] = None
    dimension_tolerance: float = field(default=0.01, metadata=ADVANCED)

    def __post_init__(self) -> None:
        """Resolve stride and preserve all historical validation messages."""
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
    "DEFAULT_REFERENCE_FILENAME_PATTERN",
    "ExtractPatchesConfig",
    "ExtractTMAConfig",
    "ExtractTissueConfig",
]
