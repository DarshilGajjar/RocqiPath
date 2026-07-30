"""Typed alignment, VALIS, ORB, and legacy registrar configurations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from rocqipath.core.magnification import DEFAULT_TARGET_MAGNIFICATION
from rocqipath.utils.naming import (
    DEFAULT_MOVING_NAME,
    DEFAULT_REFERENCE_NAME,
    build_filename_pattern,
)
from rocqipath.utils.validation import require, validate_positive

from .base import BaseConfig


@dataclass
class AlignmentConfig(BaseConfig):
    """Configure paired-slide discovery, registration, export, and QC.

    Parameters
    ----------
    input_dir, output_dir : str
        Pair-folder input root and output root.
    pair_folders : list of str
        Pair folders to process; empty enables auto-discovery.
    reference_name, moving_name : str
        Subfolder and filename-role tokens for fixed and moving slides.
    filename_pattern : str, optional
        Regex with named ``sample_id`` and ``role`` groups.
    alignment_method : {"valis", "orb"}
        Registration backend.
    aligned_wsi_level : int
        Pyramid level exported from the registered moving slide.
    patch_size : int
        Patch edge in pixels at ``target_magnification``.
    grid_density : int
        Uniform grid rows and columns.
    target_magnification : float
        Physical objective magnification for patch coordinates.
    reference_source_magnification, moving_source_magnification : float, optional
        Objective fallback when slide metadata is absent.
    valis_max_error_um : float, optional
        Maximum accepted VALIS registration error in micrometres.
    max_physical_field_ratio : float, optional
        Maximum reference-to-moving physical field ratio.
    valis_non_rigid_dim : int
        Maximum non-rigid registration dimension in processed pixels.
    valis_feature_detector : str, optional
        VALIS detector name.
    valis_num_features : int
        Maximum feature count.
    valis_check_reflections : bool
        Whether VALIS tests reflected orientations.
    valis_norm_method : str, optional
        VALIS intensity normalization method.
    keep_valis_diagnostics : bool
        Retain backend diagnostic artifacts.
    qc_enabled : bool
        Generate a center-patch QC figure.
    qc_output_dir : str, optional
        QC destination; defaults to each case output.
    qc_reference_level : int
        Reference pyramid level defining the physical QC field.
    qc_patch_size : int
        QC panel edge in output pixels.
    qc_reference_read_level, qc_moving_read_level : int
        Pyramid levels used for high-quality QC reads.
    qc_dpi : int
        QC figure dots per inch.
    dry_run : bool
        Discover and pair slides without registration.
    """

    input_dir: str = "./wsi_input"
    output_dir: str = "./wsi_output/aligned"
    pair_folders: List[str] = field(default_factory=list)
    reference_name: str = DEFAULT_REFERENCE_NAME
    moving_name: str = DEFAULT_MOVING_NAME
    filename_pattern: Optional[str] = None
    alignment_method: str = "valis"
    aligned_wsi_level: int = 0
    patch_size: int = 1024
    grid_density: int = 1
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    reference_source_magnification: Optional[float] = None
    moving_source_magnification: Optional[float] = None
    valis_max_error_um: Optional[float] = None
    max_physical_field_ratio: Optional[float] = 2.0
    valis_non_rigid_dim: int = 2048
    valis_feature_detector: Optional[str] = "disk"
    valis_num_features: int = 2000
    valis_check_reflections: bool = False
    valis_norm_method: Optional[str] = "img_stats"
    keep_valis_diagnostics: bool = True
    qc_enabled: bool = False
    qc_output_dir: Optional[str] = None
    qc_reference_level: int = 0
    qc_patch_size: int = 1024
    qc_reference_read_level: int = 0
    qc_moving_read_level: int = 0
    qc_dpi: int = 300
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Resolve and validate role names, filename matching, and zooms."""
        require(
            bool(self.reference_name and self.moving_name),
            "reference_name and moving_name must be non-empty strings.",
        )
        require(
            self.reference_name.lower() != self.moving_name.lower(),
            f"reference_name and moving_name must differ; both were {self.reference_name!r}.",
        )
        if self.filename_pattern is None:
            self.filename_pattern = build_filename_pattern(
                self.reference_name,
                self.moving_name,
            )
        try:
            compiled = re.compile(self.filename_pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"filename_pattern is not a valid regex: {exc}") from exc
        for group_name in ("sample_id", "role"):
            require(
                group_name in compiled.groupindex,
                f"filename_pattern must define named group '{group_name}'. "
                f"Pattern: {self.filename_pattern!r}",
            )
        validate_positive(
            self.target_magnification,
            name="target_magnification",
        )
        require(
            self.max_physical_field_ratio is None or self.max_physical_field_ratio >= 1,
            "max_physical_field_ratio must be >= 1 or None",
        )
        for name, value in (
            (
                "reference_source_magnification",
                self.reference_source_magnification,
            ),
            (
                "moving_source_magnification",
                self.moving_source_magnification,
            ),
        ):
            if value is not None:
                validate_positive(
                    value,
                    name=name,
                    message=f"{name} must be > 0 when supplied",
                )


@dataclass
class ValisConfig(BaseConfig):
    """Configure the VALIS rigid and non-rigid registration backend.

    Dimensions ending in ``_px`` are processed-image pixels, not level-0
    slide pixels. ``max_acceptable_error_um`` is the only physical-length
    field and is expressed in micrometres. Remaining fields map directly
    to VALIS registration options.
    """

    max_processed_image_dim_px: int = 512
    max_non_rigid_reg_dim_px: int = 2048
    max_image_dim_px: int = 1024
    thumbnail_size: int = 512
    align_to_reference: bool = True
    norm_method: Optional[str] = "img_stats"
    crop: Optional[str] = "reference"
    non_rigid_registrar_cls: Optional[object] = None
    imgs_ordered: bool = False
    micro_rigid_registrar_cls: Optional[object] = None
    micro_rigid_registrar_params: dict = field(default_factory=dict)
    run_register_micro: bool = True
    register_micro_dim_px: int = 4096
    feature_detector: Optional[str] = "disk"
    num_features: int = 2000
    rgb_features: bool = False
    check_for_reflections: bool = False
    max_acceptable_error_um: Optional[float] = None
    valis_kwargs: dict = field(default_factory=dict)
    processor_dict: Optional[dict] = None

    def __post_init__(self) -> None:
        """Instantiate VALIS' default optical-flow warper when available."""
        if self.non_rigid_registrar_cls is not None:
            return
        try:
            from valis.non_rigid_registrars import OpticalFlowWarper
        except (ImportError, OSError):
            return
        self.non_rigid_registrar_cls = OpticalFlowWarper


@dataclass
class OrbConfig(BaseConfig):
    """Configure contour-based ORB registration and validation.

    Thumbnail sizes and RANSAC thresholds are pixels in their respective
    processed thumbnail spaces. Area values are fractions, and
    ``min_ncc_threshold`` is a dimensionless normalized correlation.
    """

    n_features: int = 5000
    ransac_threshold: float = 5.0
    orb_thumb_size: int = 1500
    orb_refine_thumb_size: int = 3000
    orb_refine_enabled: bool = True
    orb_max_contours: int = 8
    orb_min_area_frac: float = 0.001
    orb_match_threshold: float = 1.4
    min_ncc_threshold: float = 0.25


@dataclass
class RegistrarDefaults(OrbConfig):
    """Typed source for the deprecated flat registrar mapping."""

    base_input_dir: str | None = None
    base_output_dir: str | None = None
    patch_size: int = 512
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    reference_source_magnification: float | None = None
    target_source_magnification: float | None = None
    grid_density: int = 20
    downsample_factor: int = 64
    overlay_max_px: int = 4000


def default_config() -> dict[str, Any]:
    """Return a fresh legacy registrar mapping derived from typed defaults."""
    defaults = RegistrarDefaults()
    legacy_order = (
        "base_input_dir",
        "base_output_dir",
        "patch_size",
        "target_magnification",
        "reference_source_magnification",
        "target_source_magnification",
        "grid_density",
        "downsample_factor",
        "n_features",
        "ransac_threshold",
        "orb_thumb_size",
        "orb_refine_thumb_size",
        "orb_refine_enabled",
        "orb_max_contours",
        "orb_min_area_frac",
        "orb_match_threshold",
        "min_ncc_threshold",
        "overlay_max_px",
    )
    return {name: getattr(defaults, name) for name in legacy_order}


__all__ = [
    "AlignmentConfig",
    "OrbConfig",
    "RegistrarDefaults",
    "ValisConfig",
    "default_config",
]
