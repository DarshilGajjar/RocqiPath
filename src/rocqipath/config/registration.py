"""Typed alignment, VALIS, and ORB configurations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

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
    """Configure paired whole-slide image discovery, registration, export, and QC.

    ``AlignmentConfig`` is the high-level configuration object for RocqiPath's
    paired-slide alignment workflow. It controls how reference and moving
    whole-slide images are discovered, paired, registered, exported, and
    optionally evaluated using quality-control figures.

    This class describes the overall RocqiPath alignment workflow rather than
    the internal details of an individual registration backend.

    Two registration backends are currently supported:

    ``"valis"``
        Uses VALIS for rigid and non-rigid whole-slide registration. This is
        generally the preferred backend for histology images that may contain
        local tissue deformation, sectioning differences, or cross-stain
        appearance changes.

    ``"orb"``
        Uses RocqiPath's lightweight ORB/contour-based registration pipeline.
        This backend primarily estimates a global geometric transformation and
        can be useful when VALIS is unavailable or when a faster,
        dependency-minimal registration method is sufficient.

    The typical directory layout expected by the alignment pipeline is::

        wsi_input/
        ├── cd8/
        │   ├── reference/
        │   │   ├── sample_0001_he.tiff
        │   │   ├── sample_0002_he.tiff
        │   │   └── ...
        │   └── moving/
        │       ├── sample_0001_cd8.tiff
        │       ├── sample_0002_cd8.tiff
        │       └── ...
        │
        └── panck/
            ├── reference/
            └── moving/

    Here, each top-level pair folder represents one alignment group or stain
    pairing. Within each pair folder, ``reference_name`` and ``moving_name``
    identify the subdirectories containing the fixed and moving slides.

    The default role names are::

        reference/
        moving/

    but these can be changed, for example::

        reference_name="he"
        moving_name="cd8"

    In addition to directory-based discovery, RocqiPath uses
    ``filename_pattern`` to extract two named values from each WSI filename:

    ``sample_id``
        The patient, specimen, block, core, or slide identifier used to pair
        the reference and moving images.

    ``role``
        The role or stain token identifying whether the image is the reference
        or moving slide.

    If ``filename_pattern`` is not supplied explicitly, RocqiPath constructs
    an appropriate regular expression from ``reference_name`` and
    ``moving_name``.

    Parameters
    ----------
    input_dir : str, default="./wsi_input"
        Root directory containing paired-slide input folders.

        Each direct child selected through ``pair_folders`` should contain the
        expected reference and moving subdirectories.

        Example::

            input_dir="./data/wsi"

        might contain::

            ./data/wsi/cd8/reference/
            ./data/wsi/cd8/moving/
            ./data/wsi/foxp3/reference/
            ./data/wsi/foxp3/moving/

        The directory must already exist before the alignment pipeline runs.

    output_dir : str, default="./wsi_output/aligned"
        Root destination for alignment outputs.

        RocqiPath creates the required alignment output structure beneath this
        directory. Depending on the selected backend and configuration,
        outputs can include:

        - aligned moving WSIs,
        - registration manifests,
        - VALIS working files,
        - registration diagnostics,
        - grid maps,
        - QC figures,
        - backend-specific intermediate artifacts.

        The directory is created automatically if necessary.

    pair_folders : list of str, default=[]
        Names of pair folders beneath ``input_dir`` that should be processed.

        For example::

            pair_folders=["cd8", "panck"]

        causes RocqiPath to process only::

            input_dir/cd8/
            input_dir/panck/

        An empty list enables automatic pair-folder discovery. RocqiPath scans
        ``input_dir`` and identifies folders containing the expected
        ``reference_name`` and/or ``moving_name`` subdirectories.

        Explicitly specifying ``pair_folders`` can be useful when a study
        contains multiple stains but only a subset should be registered.

    reference_name : str, default=DEFAULT_REFERENCE_NAME
        Directory and filename-role token representing the fixed/reference
        image.

        In a typical H&E/IHC workflow, the H&E slide is used as the reference
        because downstream patch coordinates and aligned WSI geometry are
        commonly defined relative to H&E.

        Example::

            reference_name="he"

        may correspond to::

            cd8/he/
            sample_0001_he.tiff

        ``reference_name`` must be non-empty and must differ from
        ``moving_name`` ignoring capitalization.

    moving_name : str, default=DEFAULT_MOVING_NAME
        Directory and filename-role token representing the image that will be
        transformed into the reference coordinate system.

        In an H&E/CD8 registration workflow, for example::

            reference_name="he"
            moving_name="cd8"

        means H&E remains spatially fixed while the CD8 image is warped to
        match H&E.

        ``moving_name`` must be non-empty and must differ from
        ``reference_name`` ignoring capitalization.

    filename_pattern : str or None, default=None
        Regular expression used to parse WSI filenames and identify
        ``sample_id`` and ``role``.

        The expression must contain both named capture groups::

            (?P<sample_id>...)
            (?P<role>...)

        For example::

            r"(?P<sample_id>.+?)_(?P<role>he|cd8)\\.(tif|tiff|svs)$"

        can parse filenames such as::

            sample_0001_he.tiff
            sample_0001_cd8.tiff

        into::

            sample_id = "sample_0001"
            role = "he"

        If ``None``, RocqiPath automatically constructs a filename pattern
        using ``reference_name`` and ``moving_name``.

        The regular expression is compiled case-insensitively.

        Invalid regular expressions or expressions lacking the required named
        groups raise ``ValueError``.

    alignment_method : {"valis", "orb"}, default="valis"
        Registration backend used for paired-slide alignment.

        ``"valis"``
            Performs VALIS-based rigid and non-rigid WSI registration.

        ``"orb"``
            Performs RocqiPath's ORB/contour-based affine registration.

        VALIS is generally preferred when accurate cross-stain registration
        and local deformation correction are required.

        ORB is useful as a lightweight fallback or when only approximate
        global geometric alignment is necessary.

    aligned_wsi_level : int, default=0
        Reference-slide pyramid level used when exporting the aligned moving
        WSI.

        Whole-slide images usually contain multiple pyramid levels:

        - level 0: highest/native resolution,
        - level 1: downsampled representation,
        - level 2: further downsampled,
        - and so on.

        ``aligned_wsi_level=0`` exports the registered moving image on the
        reference slide's level-0 coordinate canvas.

        Higher values reduce output resolution and storage requirements.

        This parameter refers to the pyramid level of the exported aligned
        image and is independent of the internal registration resolution used
        by VALIS or ORB.

    patch_size : int, default=1024
        Edge length, in pixels, of patches generated or evaluated by the
        registration grid at ``target_magnification``.

        For example::

            patch_size=1024

        represents a square field of::

            1024 x 1024 pixels

        at the configured target magnification.

        ``patch_size`` does not define the internal VALIS or ORB registration
        image size.

    grid_density : int, default=1
        Number of uniform grid divisions along each spatial dimension when
        constructing the registration grid map.

        Conceptually::

            grid_density=1

        corresponds to one large grid region, while::

            grid_density=4

        produces approximately a::

            4 x 4

        spatial grid before tissue-validity filtering.

        The exact number of usable grid regions may be smaller because
        background or insufficient-tissue regions can be rejected.

        Increasing ``grid_density`` provides finer spatial sampling for patch
        extraction but may generate many more candidate grid cells.

    target_magnification : float, default=DEFAULT_TARGET_MAGNIFICATION
        Physical objective magnification used by RocqiPath for standardized
        patch coordinates and magnification-aware image operations.

        Typical values include::

            10.0
            20.0
            40.0

        For example::

            target_magnification=20.0

        requests coordinates and patch fields corresponding to approximately
        20x objective magnification regardless of the native scanner
        magnification.

        RocqiPath uses slide metadata and pyramid downsampling information to
        determine how this physical target maps onto each WSI.

        This value must be strictly greater than zero.

    reference_source_magnification : float or None, default=None
        Explicit level-0 objective magnification of the reference slide.

        Normally RocqiPath obtains the source magnification from OpenSlide
        metadata such as::

            openslide.objective-power

        or derives an estimate from physical pixel size when appropriate.

        This field provides a manual fallback or override when slide metadata
        is unavailable, missing, unreliable, or known to be incorrect.

        Example::

            reference_source_magnification=80.0

        indicates that the reference WSI was scanned at approximately 80x
        native magnification.

        ``None`` allows RocqiPath to determine the value automatically.

        When supplied, this value must be strictly positive.

    moving_source_magnification : float or None, default=None
        Explicit level-0 objective magnification of the moving slide.

        This serves the same purpose as
        ``reference_source_magnification`` but is applied independently to the
        moving WSI.

        Independent values are important because the two slides may have been
        scanned using different scanners, objective powers, or pixel sizes.

        Example::

            reference_source_magnification=80.0
            moving_source_magnification=20.0

        is valid when the reference and moving slides truly originate from
        different native resolutions.

        ``None`` allows RocqiPath to determine the moving-slide magnification
        from available metadata.

        When supplied, this value must be strictly positive.

    valis_config : ValisConfig or None, default=None
        Complete VALIS backend configuration.

        This is the preferred interface for advanced VALIS registration
        configuration. It allows feature detectors, feature matchers,
        sorting/orientation matchers, registration resolutions, non-rigid
        registration, micro-registration, and other VALIS-specific options
        to be configured through a dedicated ``ValisConfig`` object.

        When supplied, this configuration takes precedence over the legacy
        ``valis_*`` convenience fields defined directly on
        ``AlignmentConfig``.

        Example::

            valis_cfg = ValisConfig(
                feature_detector="disk",
                matcher="lightglue",
                num_features=3000,
                sorting_feature_detector="brisk",
                sorting_matcher="descriptor",
            )

            cfg = AlignmentConfig(
                input_dir="./wsi_input",
                output_dir="./wsi_output/aligned",
                alignment_method="valis",
                valis_config=valis_cfg,
            )

        ``None`` preserves the legacy behavior, where RocqiPath constructs a
        ``ValisConfig`` internally from ``valis_max_error_um``,
        ``valis_non_rigid_dim``, ``valis_feature_detector``,
        ``valis_num_features``, ``valis_check_reflections``, and
        ``valis_norm_method``.    
    
    valis_max_error_um : float or None, default=None
        Maximum accepted VALIS registration error, expressed in micrometres.

        After VALIS completes registration, RocqiPath can compare registration
        error estimates against this physical threshold.

        Example::

            valis_max_error_um=100.0

        can be used to flag registrations whose reported physical alignment
        error exceeds approximately 100 micrometres.

        ``None`` disables this explicit acceptance threshold.

        This field applies only when ``alignment_method="valis"``.

    max_physical_field_ratio : float or None, default=2.0
        Maximum allowed ratio between the physical fields covered by the
        reference and moving slides.

        Before registration, RocqiPath can compare the physical dimensions of
        the two WSIs to detect highly mismatched slide extents.

        Conceptually, if the larger physical field is divided by the smaller
        physical field, the resulting ratio should not exceed this threshold.

        For example::

            max_physical_field_ratio=2.0

        means that one slide may cover up to approximately twice the physical
        field of the other before the mismatch is considered unusually large.

        This check is useful for detecting problems such as:

        - incorrect magnification metadata,
        - accidental pairing of unrelated slides,
        - drastically different scan regions,
        - incorrect source-magnification overrides.

        ``None`` disables the physical-field-ratio check.

        When supplied, the value must be at least ``1.0``.

    valis_non_rigid_dim : int, default=2048
        Maximum processed-image dimension, in pixels, used for VALIS
        non-rigid registration.

        This high-level convenience field is forwarded to
        ``ValisConfig.max_non_rigid_reg_dim_px`` by the current alignment
        pipeline.

        Larger values provide more spatial information for local deformation
        estimation but increase memory consumption and runtime.

        This field applies only when ``alignment_method="valis"``.

        In a more advanced workflow where a complete ``ValisConfig`` is
        supplied separately, the corresponding value in that configuration
        should be considered the more specific backend setting.

    valis_feature_detector : str or None, default="disk"
        Feature detector used by the VALIS rigid-registration stage.

        The default ``"disk"`` selects DISK-based feature detection.

        Depending on the RocqiPath and VALIS versions, other supported
        detectors may include options such as::

            "dedode"
            "superpoint"
            "brisk"
            "orb"
            "kaze"
            "akaze"
            "vgg"

        This field is intended as a convenient high-level configuration option.

        More advanced detector-specific settings should generally be supplied
        through ``ValisConfig``.

    valis_num_features : int, default=2000
        Maximum or target number of image features detected by compatible
        VALIS feature detectors.

        Increasing this value can provide more candidate correspondences when
        tissue is complex or sparsely matched, but also increases matching
        runtime and memory usage.

        This value is forwarded to ``ValisConfig.num_features``.

        It applies only to detectors that support explicit feature-count
        control.

    valis_check_reflections : bool, default=False
        Whether VALIS should evaluate reflected or mirrored orientations while
        searching for an alignment.

        Set this to ``True`` when slide orientation is uncertain or when
        scanner/export behavior may have introduced left-right or other mirror
        reflections.

        Reflection checking increases registration search complexity and may
        therefore increase runtime.

    valis_norm_method : str or None, default="img_stats"
        VALIS image-intensity normalization method used during registration
        preprocessing.

        ``"img_stats"`` is the default RocqiPath setting and provides a
        general image-statistics-based normalization strategy.

        Cross-stain histology registration can benefit from preprocessing
        because the corresponding biological structures may have very
        different raw pixel intensities between H&E and IHC slides.

        ``None`` allows VALIS to determine its own default behavior.

    keep_valis_diagnostics : bool, default=True
        Whether VALIS diagnostic and intermediate artifacts should be retained
        after registration.

        When ``True``, backend-generated diagnostic files can remain available
        for registration inspection, debugging, and quality assessment.

        When ``False``, RocqiPath may remove unnecessary VALIS temporary or
        diagnostic data after the registration output has been successfully
        generated.

        Keeping diagnostics is useful during method development and parameter
        optimization but can consume substantial disk space in large studies.

    qc_enabled : bool, default=False
        Whether RocqiPath should generate an additional registration
        quality-control image for each successfully aligned pair.

        When enabled, the alignment pipeline creates a representative
        side-by-side or center-region comparison between the reference and
        aligned moving image.

        These QC figures are intended for rapid visual review rather than as a
        replacement for quantitative registration metrics.

    qc_output_dir : str or None, default=None
        Destination directory for alignment QC figures.

        When ``None``, QC output defaults to the corresponding case output
        directory generated by the alignment pipeline.

        Example::

            qc_output_dir="./wsi_output/qc"

        allows all QC figures to be collected in one dedicated location.

        This field has no effect when ``qc_enabled=False``.

    qc_reference_level : int, default=0
        Reference-slide pyramid level used to define the physical field shown
        in the QC comparison.

        ``0`` corresponds to the highest-resolution reference level.

        Higher pyramid levels define progressively larger effective fields of
        view for the same nominal patch dimensions because the image is more
        heavily downsampled.

    qc_patch_size : int, default=1024
        Edge length, in output pixels, of the representative QC region.

        For example::

            qc_patch_size=1024

        produces a nominal::

            1024 x 1024

        QC field after the corresponding reference and moving regions are
        read and displayed.

        This parameter controls the QC panel size and does not affect the
        registration itself.

    qc_reference_read_level : int, default=0
        Pyramid level used to read the reference image when generating the QC
        figure.

        This can be controlled separately from ``qc_reference_level`` so that
        the physical field of view and the image-reading resolution can be
        adjusted independently.

        Using higher-resolution reads can improve QC image sharpness but may
        increase memory usage and I/O cost.

    qc_moving_read_level : int, default=0
        Pyramid level used to read the aligned moving image when generating
        the QC figure.

        This is the moving-slide counterpart to
        ``qc_reference_read_level``.

        When possible, corresponding reference and moving QC reads should
        represent comparable physical resolutions.

    qc_dpi : int, default=300
        Resolution, in dots per inch, used when saving QC figures.

        ``300`` is suitable for most reports and presentation figures.

        Higher values such as ``600`` can be useful for publication-quality
        raster outputs but increase file size.

        This setting affects only the saved QC figure and does not affect the
        WSI registration or aligned WSI resolution.

    dry_run : bool, default=False
        Whether to perform slide discovery and pairing without executing
        registration.

        When ``True``, RocqiPath:

        - discovers pair folders,
        - indexes reference and moving images,
        - applies filename parsing,
        - builds slide pairs,
        - reports the discovered workflow,

        but does not register or export aligned WSIs.

        This is useful for validating directory structure, filenames, regex
        patterns, role assignments, and pairing logic before running an
        expensive registration job.

    Notes
    -----
    High-level versus backend configuration
        ``AlignmentConfig`` controls the overall paired-slide workflow.

        VALIS-specific algorithmic settings belong conceptually to
        ``ValisConfig`` and ORB-specific algorithmic settings belong to
        ``OrbConfig``.

        The existing ``valis_*`` fields in ``AlignmentConfig`` provide
        convenient high-level controls and preserve backward compatibility.

    Reference coordinate system
        In the typical RocqiPath workflow, the reference image defines the
        output spatial coordinate system. The moving image is transformed to
        align with the reference.

    Magnification
        ``target_magnification`` describes a physical image scale, whereas
        ``aligned_wsi_level`` and the various ``qc_*_level`` fields describe
        WSI pyramid levels.

        These concepts should not be treated as interchangeable.

    Pairing
        Pairing is based on the ``sample_id`` extracted using
        ``filename_pattern``. A valid reference and moving file with the same
        ``sample_id`` are required for a complete pair.

    Directory discovery
        When ``pair_folders`` is empty, RocqiPath attempts to discover pair
        folders automatically beneath ``input_dir``.

    Physical-field validation
        ``max_physical_field_ratio`` is intended to identify suspicious
        differences between reference and moving slide coverage before
        registration. A large mismatch does not necessarily imply incorrect
        data, but it is often worth reviewing.

    QC
        The optional QC output provides visual inspection of registration
        quality. Quantitative registration metrics and direct WSI inspection
        should still be used when registration accuracy is scientifically
        important.

    Examples
    --------
    Run VALIS registration with the default configuration:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ... )

    Process only selected stain folders:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ...     pair_folders=["cd8", "panck"],
    ... )

    Use custom role names:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ...     reference_name="he",
    ...     moving_name="cd8",
    ... )

    Use an explicit filename pattern:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ...     reference_name="he",
    ...     moving_name="cd8",
    ...     filename_pattern=(
    ...         r"(?P<sample_id>.+?)_"
    ...         r"(?P<role>he|cd8)\\.(tif|tiff|svs)$"
    ...     ),
    ... )

    Register at 20x while explicitly defining native slide magnifications:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ...     target_magnification=20.0,
    ...     reference_source_magnification=80.0,
    ...     moving_source_magnification=20.0,
    ... )

    Configure the high-level VALIS feature settings:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ...     alignment_method="valis",
    ...     valis_non_rigid_dim=2048,
    ...     valis_feature_detector="disk",
    ...     valis_num_features=3000,
    ...     valis_check_reflections=True,
    ... )

    Use the lightweight ORB registration backend:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ...     alignment_method="orb",
    ... )

    Enable visual registration QC:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ...     qc_enabled=True,
    ...     qc_patch_size=1024,
    ...     qc_dpi=600,
    ... )

    Validate slide discovery and pairing without registration:

    >>> cfg = AlignmentConfig(
    ...     input_dir="./wsi_input",
    ...     output_dir="./wsi_output/aligned",
    ...     dry_run=True,
    ... )
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

    max_physical_field_ratio: Optional[float] = None

    # ------------------------------------------------------------------
    # VALIS backend configuration
    # ------------------------------------------------------------------

    # Preferred advanced API.
    valis_config: Optional["ValisConfig"] = None

    # Legacy/high-level convenience options retained for compatibility.
    valis_max_error_um: Optional[float] = None
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
        """Resolve derived settings and validate alignment configuration.

        This method performs configuration checks immediately after dataclass
        initialization so invalid slide-discovery or physical-resolution
        settings fail before expensive registration begins.

        Validation currently includes:

        1. Ensuring ``reference_name`` and ``moving_name`` are both non-empty.
        2. Ensuring the two role names are not identical when compared
           case-insensitively.
        3. Automatically constructing ``filename_pattern`` when one was not
           supplied.
        4. Compiling ``filename_pattern`` as a case-insensitive regular
           expression.
        5. Verifying that the pattern contains both required named groups:
           ``sample_id`` and ``role``.
        6. Ensuring ``target_magnification`` is strictly positive.
        7. Ensuring ``max_physical_field_ratio`` is either ``None`` or at
           least ``1``.
        8. Ensuring explicit reference and moving source magnifications are
           strictly positive when supplied.

        Raises
        ------
        ValueError
            If role names are invalid, the filename regular expression cannot
            be compiled, required named regex groups are missing, a supplied
            magnification is invalid, or the physical-field-ratio constraint
            is invalid.

        Notes
        -----
        The automatically generated filename pattern is based on the current
        ``reference_name`` and ``moving_name`` values. Therefore, those role
        names should be finalized before configuration initialization
        completes.

        This method validates configuration semantics only. It does not open
        WSI files, inspect image metadata, discover pair folders, or execute
        registration.
        """

        # Convert serialized VALIS configuration back into ValisConfig.
        if isinstance(self.valis_config, dict):
            self.valis_config = ValisConfig.from_dict(
                self.valis_config
            )

        require(
            bool(self.reference_name and self.moving_name),
            "reference_name and moving_name must be non-empty strings.",
        )

        require(
            self.reference_name.lower() != self.moving_name.lower(),
            f"reference_name and moving_name must differ; "
            f"both were {self.reference_name!r}.",
        )

        if self.filename_pattern is None:
            self.filename_pattern = build_filename_pattern(
                self.reference_name,
                self.moving_name,
            )

        try:
            compiled = re.compile(
                self.filename_pattern,
                re.IGNORECASE,
            )
        except re.error as exc:
            raise ValueError(
                f"filename_pattern is not a valid regex: {exc}"
            ) from exc

        for group_name in (
            "sample_id",
            "role",
        ):
            require(
                group_name in compiled.groupindex,
                f"filename_pattern must define named group "
                f"'{group_name}'. Pattern: "
                f"{self.filename_pattern!r}",
            )

        validate_positive(
            self.target_magnification,
            name="target_magnification",
        )

        require(
            self.max_physical_field_ratio is None
            or self.max_physical_field_ratio >= 1,
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
    """Configure the VALIS rigid and non-rigid whole-slide registration backend.

    ``ValisConfig`` provides the advanced configuration surface used by
    RocqiPath when registration is performed with the VALIS backend. It
    controls image resolution, feature detection, feature matching, slide
    orientation, rigid registration, non-rigid registration, optional
    high-resolution micro-registration, image preprocessing, registration
    quality thresholds, and direct passthrough arguments to VALIS.

    The purpose of this class is to expose VALIS-specific registration
    parameters without requiring users to modify RocqiPath's internal
    registration implementation.

    In a typical workflow, a ``ValisConfig`` instance is created separately
    and supplied to the alignment pipeline. Simple users can rely entirely on
    the defaults, while advanced users can modify feature detectors, feature
    matchers, registration resolutions, or native VALIS options.

    The default configuration is designed for general-purpose H&E-to-IHC
    whole-slide image registration using the modern VALIS registration stack:

    - DISK feature detection.
    - Automatic selection of the corresponding feature matcher.
    - Up to 2,000 detected features.
    - Grayscale feature detection.
    - Registration to the supplied reference image.
    - 512-pixel processed images for rigid feature registration.
    - 2,048-pixel processed images for non-rigid registration.
    - VALIS ``OpticalFlowWarper`` for non-rigid registration when available.

    Parameters
    ----------
    max_processed_image_dim_px : int, default=512
        Maximum dimension, in pixels, of the processed images used primarily
        for VALIS rigid registration and feature matching.

        VALIS creates lower-resolution representations of the original
        whole-slide images before detecting and matching image features.
        Limiting this dimension greatly reduces memory consumption and runtime
        because feature detection does not need to operate directly on the
        full-resolution WSI.

        For example, if the original slide dimensions are approximately
        ``80,000 x 60,000`` pixels and this parameter is ``512``, VALIS creates
        a processed representation whose longest dimension is approximately
        512 pixels while preserving the slide aspect ratio.

        Larger values can expose more tissue detail and may improve feature
        matching when the tissue contains relatively small or sparse
        structures. However, they also increase registration runtime, memory
        use, and the number of potentially ambiguous local features.

        This parameter affects the scale at which the primary rigid
        registration is estimated. It does not define the resolution of the
        final exported aligned WSI.

    max_non_rigid_reg_dim_px : int, default=2048
        Maximum processed-image dimension, in pixels, used by VALIS for the
        primary non-rigid registration stage.

        Non-rigid registration estimates local tissue deformation after the
        initial rigid registration has approximately aligned the slides.
        Because local deformation requires more spatial information than rigid
        feature matching, this value is normally larger than
        ``max_processed_image_dim_px``.

        Increasing this value may improve local correspondence between
        histologic structures, particularly when consecutive sections contain
        bending, stretching, compression, or sectioning artifacts. The cost is
        substantially higher memory usage and longer registration time.

        This value should normally satisfy::

            max_non_rigid_reg_dim_px > max_processed_image_dim_px

        especially when a meaningful deformable registration step is desired.

    max_image_dim_px : int, default=1024
        Maximum image dimension passed to the underlying VALIS registration
        object for general image-processing operations.

        This is distinct from ``max_processed_image_dim_px`` and
        ``max_non_rigid_reg_dim_px``. VALIS may use this value while generating
        intermediate image representations, thumbnails, or registration
        images depending on the installed VALIS version.

        In most workflows this value can remain at its default unless a
        particular VALIS configuration requires larger image representations.

    thumbnail_size : int, default=512
        Requested thumbnail dimension, in pixels, used by VALIS for
        low-resolution visualization and internal image handling where
        applicable.

        This parameter does not determine the resolution of the final aligned
        WSI and should generally remain relatively small.

    align_to_reference : bool, default=True
        Whether the registered image set should be explicitly aligned to the
        designated reference image.

        When ``True``, the reference slide acts as the fixed spatial anchor.
        For a typical H&E/IHC workflow, H&E remains fixed and the IHC slide is
        transformed into the H&E coordinate system.

        When ``False``, VALIS may construct a common or consensus registration
        space rather than preserving the original reference-image coordinate
        system exactly.

        RocqiPath generally recommends ``True`` for paired-slide workflows
        because downstream aligned patch extraction usually assumes that the
        reference slide defines the coordinate system.

    norm_method : str or None, default="img_stats"
        VALIS intensity normalization method used during registration image
        preprocessing.

        Registration between differently stained histology images is difficult
        because corresponding structures may have very different RGB or
        grayscale intensities. VALIS therefore preprocesses images before
        feature detection and registration.

        ``"img_stats"`` uses image-statistics-based normalization and is a
        suitable general default.

        Setting this value to ``None`` prevents RocqiPath from explicitly
        supplying a normalization method, allowing the installed VALIS version
        to choose its own default behavior.

    crop : str or None, default="reference"
        Cropping strategy supplied to VALIS.

        ``"reference"`` instructs VALIS to use the reference image as the
        spatial basis for the resulting registered field where supported.

        Cropping behavior affects how much of the warped image canvas is
        retained after registration. This is especially important when the
        reference and moving slides contain different tissue extents or were
        scanned with different surrounding margins.

        Setting this value to ``None`` leaves cropping behavior to VALIS.

    imgs_ordered : bool, default=False
        Whether the input images are already supplied in their known physical
        or serial-section order.

        For large multi-slide registration studies, VALIS can determine image
        ordering using image similarity and feature matching. When
        ``imgs_ordered=True``, the supplied image ordering is treated as known
        and the corresponding sorting stage can be reduced or bypassed,
        depending on VALIS behavior.

        For simple two-slide H&E/IHC pairs this setting usually has little
        practical effect and can remain ``False``.

    check_for_reflections : bool, default=False
        Whether VALIS should evaluate reflected image orientations during
        registration.

        This option can help when one slide may have been scanned or stored
        with a mirrored orientation relative to another slide.

        Reflection checking increases the number of candidate transformations
        that must be evaluated and therefore increases registration runtime.

        Set this to ``True`` when slide orientation is uncertain or when
        mirrored registration failures have been observed.

    non_rigid_registrar_cls : object or None, default=None
        VALIS non-rigid registration class or registrar implementation.

        When ``None``, RocqiPath attempts to lazily import and use VALIS'
        ``OpticalFlowWarper``.

        Advanced users may provide another compatible VALIS non-rigid
        registration implementation, such as a different optical-flow or
        deformable-registration backend supported by the installed VALIS
        version.

        This field accepts the actual Python class or object expected by VALIS,
        not a string name.

        The lazy default initialization is intentional. Importing VALIS can be
        expensive and may initialize deep-learning components, so RocqiPath
        avoids importing VALIS until the functionality is actually required.

    micro_rigid_registrar_cls : object or None, default=None
        Optional VALIS registrar used for high-resolution micro-rigid
        refinement.

        Micro-registration is an additional refinement stage performed after
        the primary registration. It can improve correspondence of smaller
        tissue structures when the initial rigid and non-rigid transforms are
        already reasonably accurate.

        ``None`` uses the VALIS default behavior where applicable.

    micro_rigid_registrar_params : dict, default={}
        Additional keyword arguments supplied to the configured
        ``micro_rigid_registrar_cls``.

        The accepted keys depend on the specific VALIS micro-registration
        implementation being used.

        Example::

            micro_rigid_registrar_params={
                "some_parameter": 10,
            }

        Empty by default.

    run_register_micro : bool, default=False
        Whether to execute VALIS' optional high-resolution micro-registration
        stage after the standard registration pipeline.

        When enabled, RocqiPath calls the corresponding VALIS
        ``register_micro`` workflow after the initial rigid and non-rigid
        registration.

        Micro-registration can substantially increase runtime and memory
        requirements. It is therefore disabled by default.

    register_micro_dim_px : int, default=4096
        Maximum processed-image dimension, in pixels, used during optional
        micro-registration.

        This should normally be larger than
        ``max_non_rigid_reg_dim_px`` because the purpose of micro-registration
        is to refine registration at a higher spatial resolution.

        For example::

            max_processed_image_dim_px = 512
            max_non_rigid_reg_dim_px = 2048
            register_micro_dim_px = 4096

        defines progressively finer registration stages.

        If micro-registration is disabled through ``run_register_micro=False``,
        this value has no effect.

    feature_detector : str or None, default="disk"
        Name of the feature detector used for the primary rigid registration.

        RocqiPath resolves this name against supported VALIS feature detectors.
        The intended modern default is ``"disk"``, corresponding to VALIS'
        ``DiskFD`` detector.

        Depending on the installed VALIS version and RocqiPath matcher builder,
        possible choices may include detectors such as::

            "disk"
            "dedode"
            "superpoint"
            "brisk"
            "orb"
            "kaze"
            "akaze"
            "vgg"

        The selected feature detector determines how local image landmarks are
        identified before correspondence matching.

        Deep feature detectors such as DISK or DeDoDe are generally useful for
        difficult cross-stain histology registration, whereas classical
        detectors such as BRISK or ORB can be useful when rotation invariance,
        speed, or lower computational requirements are important.

        When ``None``, RocqiPath does not explicitly construct a feature
        matcher from this field and VALIS may fall back to its native defaults.

    num_features : int, default=2000
        Maximum or target number of detected image features where supported by
        the selected detector.

        This is primarily a convenience option for feature detectors such as
        DISK and DeDoDe.

        Increasing this value creates more potential correspondences and may
        improve registration when tissue is heterogeneous or sparse. However,
        more features also increase feature-matching cost and may introduce
        additional incorrect correspondences.

        Explicit values supplied inside ``feature_detector_kwargs`` should be
        considered more advanced detector-specific configuration and may
        override this convenience field depending on the matcher builder.

    rgb_features : bool, default=False
        Whether compatible feature detectors should operate on RGB image data
        rather than the processed single-channel registration image.

        ``False`` uses grayscale or VALIS-processed image representations and
        corresponds to the modern VALIS default for DISK-based registration.

        ``True`` can preserve stain-specific color information and may improve
        registration in some datasets, but its usefulness depends strongly on
        stain pairing and image appearance.

        This option is only meaningful for feature detectors that explicitly
        support RGB operation, such as compatible Kornia-based detectors.

    matcher : str, default="auto"
        Feature-matching strategy used with ``feature_detector``.

        ``"auto"`` instructs RocqiPath to determine an appropriate matcher
        based on the selected feature detector.

        Typical automatically resolved combinations include::

            DISK       -> LightGlue
            DeDoDe     -> LightGlue
            SuperPoint -> SuperGlue
            BRISK      -> generic descriptor matcher
            ORB        -> generic descriptor matcher

        Advanced users may explicitly request a supported matcher, for example::

            matcher="lightglue"
            matcher="superglue"
            matcher="descriptor"

        The exact available matcher names depend on RocqiPath's matcher
        resolver and the installed VALIS version.

        Explicit detector/matcher combinations should be chosen carefully.
        Some matchers are designed only for specific descriptor families.

    feature_detector_kwargs : dict, default={}
        Additional keyword arguments passed directly to the selected VALIS
        feature detector when RocqiPath constructs it.

        This provides detector-specific control beyond the generic
        ``num_features`` and ``rgb_features`` fields.

        Example::

            feature_detector_kwargs={
                "num_features": 4000,
                "rgb": True,
                "device": "cuda",
            }

        Valid keys depend entirely on the selected feature-detector class and
        installed VALIS version.

        This field is intended for advanced configuration and allows RocqiPath
        to expose future VALIS detector options without requiring a dedicated
        dataclass field for every upstream parameter.

    matcher_kwargs : dict, default={}
        Additional keyword arguments passed directly to the selected VALIS
        feature matcher.

        Examples may include matcher-specific confidence thresholds,
        RANSAC/USAC parameters, descriptor matching options, or neural matcher
        parameters.

        Example::

            matcher_kwargs={
                "match_filter_method": "USAC_MAGSAC",
                "ransac_thresh": 7,
            }

        For a SuperGlue-based matcher, a configuration might instead include
        parameters such as matching thresholds or iteration counts.

        The accepted arguments depend on the matcher class provided by the
        installed VALIS version.

    sorting_feature_detector : str or None, default=None
        Optional feature detector used specifically during VALIS image
        sorting and initial orientation estimation.

        VALIS can use a different detector for image ordering/orientation than
        for the main rigid registration. This is particularly useful when the
        primary high-performance feature detector is not rotation invariant.

        For example, DISK may be used for final rigid matching while BRISK is
        used to estimate initial orientation::

            feature_detector="disk"
            matcher="lightglue"
            sorting_feature_detector="brisk"
            sorting_matcher="descriptor"

        When ``None``, RocqiPath does not explicitly construct a separate
        sorting detector and VALIS retains its normal/default sorting behavior.

    sorting_matcher : str or None, default=None
        Optional matcher paired with ``sorting_feature_detector``.

        This matcher is used for the image sorting/orientation stage rather
        than the final rigid feature-matching stage.

        ``None`` means that RocqiPath does not explicitly request a separate
        sorting matcher unless the surrounding matcher-building logic chooses
        one automatically.

    sorting_feature_detector_kwargs : dict, default={}
        Additional keyword arguments passed to the sorting/orientation feature
        detector.

        This is equivalent to ``feature_detector_kwargs`` but applies only to
        ``sorting_feature_detector``.

        Example::

            sorting_feature_detector_kwargs={
                "n_levels": 4,
            }

        Valid keys depend on the selected VALIS feature detector.

    sorting_matcher_kwargs : dict, default={}
        Additional keyword arguments supplied to the feature matcher used for
        image sorting/orientation.

        This is equivalent to ``matcher_kwargs`` but applies only to
        ``sorting_matcher``.

        The accepted values depend on the selected VALIS matcher.

    max_acceptable_error_um : float or None, default=None
        Maximum registration error accepted by RocqiPath, expressed in
        micrometres.

        After VALIS registration, RocqiPath can inspect the registration error
        metrics produced by VALIS and compare them against this threshold.

        If the measured error exceeds the threshold, RocqiPath may flag the
        registration according to the surrounding quality-control logic.

        ``None`` disables this explicit physical-error threshold.

        Unlike the ``*_dim_px`` parameters, this field is expressed in a
        physical unit rather than processed-image pixels.

    valis_kwargs : dict, default={}
        Arbitrary keyword arguments passed directly to
        ``valis.registration.Valis``.

        This is the advanced escape hatch for functionality that does not yet
        have a dedicated ``ValisConfig`` field.

        Values in ``valis_kwargs`` should be applied after RocqiPath constructs
        its standard VALIS argument dictionary. Therefore, when the same key
        exists in both places, the value in ``valis_kwargs`` can intentionally
        override RocqiPath's generated value.

        Example::

            valis_kwargs={
                "matcher": custom_matcher,
                "matcher_for_sorting": custom_sorting_matcher,
            }

        This mechanism is especially useful when experimenting with newly
        introduced VALIS parameters before RocqiPath explicitly exposes them.

        Because these arguments are passed to the installed VALIS version,
        unsupported keys may cause VALIS to raise ``TypeError`` or another
        configuration error.

    processor_dict : dict or None, default=None
        Optional processor configuration passed to VALIS during registration.

        VALIS supports custom image preprocessing pipelines for individual
        images or image classes. ``processor_dict`` allows advanced users to
        provide those processor mappings directly through RocqiPath.

        This can be useful when different stains require different
        preprocessing before feature detection or non-rigid registration.

        ``None`` uses VALIS' normal preprocessing behavior.

    Notes
    -----
    Pixel dimensions
        Fields ending in ``_px`` describe dimensions of processed registration
        images, not level-0 WSI dimensions.

    Physical error
        ``max_acceptable_error_um`` is expressed in micrometres and is
        therefore fundamentally different from the processed-image pixel
        dimensions.

    Feature matching
        Feature detection and feature matching are separate operations.
        ``feature_detector`` determines where and how image landmarks are
        detected, whereas ``matcher`` determines how those landmarks are
        associated between images.

    Sorting versus registration
        ``sorting_feature_detector`` and ``sorting_matcher`` can be different
        from the primary ``feature_detector`` and ``matcher``. This allows a
        rotation-invariant detector to estimate image orientation before a
        more powerful learned detector performs the final rigid matching.

    Performance
        Increasing registration dimensions or feature counts can improve
        registration quality, but usually increases GPU/CPU memory use,
        processing time, and feature-matching complexity.

    Examples
    --------
    Use the default VALIS configuration:

    >>> cfg = ValisConfig()

    Use more DISK features:

    >>> cfg = ValisConfig(
    ...     feature_detector="disk",
    ...     matcher="lightglue",
    ...     num_features=4000,
    ... )

    Use RGB DISK features:

    >>> cfg = ValisConfig(
    ...     feature_detector="disk",
    ...     matcher="lightglue",
    ...     num_features=3000,
    ...     rgb_features=True,
    ... )

    Use DeDoDe with LightGlue:

    >>> cfg = ValisConfig(
    ...     feature_detector="dedode",
    ...     matcher="lightglue",
    ...     num_features=3000,
    ... )

    Use a separate rotation-invariant detector for image orientation:

    >>> cfg = ValisConfig(
    ...     feature_detector="disk",
    ...     matcher="lightglue",
    ...     sorting_feature_detector="brisk",
    ...     sorting_matcher="descriptor",
    ... )

    Enable higher-resolution micro-registration:

    >>> cfg = ValisConfig(
    ...     max_processed_image_dim_px=512,
    ...     max_non_rigid_reg_dim_px=2048,
    ...     run_register_micro=True,
    ...     register_micro_dim_px=4096,
    ... )

    Supply advanced matcher parameters:

    >>> cfg = ValisConfig(
    ...     feature_detector="brisk",
    ...     matcher="descriptor",
    ...     matcher_kwargs={
    ...         "match_filter_method": "USAC_MAGSAC",
    ...         "ransac_thresh": 7,
    ...     },
    ... )

    Override a native VALIS argument directly:

    >>> cfg = ValisConfig(
    ...     valis_kwargs={
    ...         "some_future_valis_option": True,
    ...     }
    ... )
    """

    # ------------------------------------------------------------------
    # Registration resolution
    # ------------------------------------------------------------------
    max_processed_image_dim_px: int = 512
    max_non_rigid_reg_dim_px: int = 2048
    max_image_dim_px: int = 1024
    thumbnail_size: int = 512

    # ------------------------------------------------------------------
    # Registration behavior
    # ------------------------------------------------------------------
    align_to_reference: bool = True
    norm_method: Optional[str] = "img_stats"
    crop: Optional[str] = "reference"
    imgs_ordered: bool = False
    check_for_reflections: bool = False

    # ------------------------------------------------------------------
    # Non-rigid registration
    # ------------------------------------------------------------------
    non_rigid_registrar_cls: Optional[object] = None

    # ------------------------------------------------------------------
    # Micro registration
    # ------------------------------------------------------------------
    micro_rigid_registrar_cls: Optional[object] = None
    micro_rigid_registrar_params: dict = field(default_factory=dict)
    run_register_micro: bool = False
    register_micro_dim_px: int = 4096

    # ------------------------------------------------------------------
    # Main rigid feature detector / matcher
    # ------------------------------------------------------------------
    feature_detector: Optional[str] = "disk"

    # Existing convenience options retained for backward compatibility.
    num_features: int = 2000
    rgb_features: bool = False

    matcher: str = "auto"
    feature_detector_kwargs: dict = field(default_factory=dict)
    matcher_kwargs: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Feature detector / matcher used during image sorting/orientation
    # ------------------------------------------------------------------
    sorting_feature_detector: Optional[str] = None
    sorting_matcher: Optional[str] = None

    sorting_feature_detector_kwargs: dict = field(default_factory=dict)
    sorting_matcher_kwargs: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Quality
    # ------------------------------------------------------------------
    max_acceptable_error_um: Optional[float] = None

    # ------------------------------------------------------------------
    # Advanced VALIS escape hatch
    # ------------------------------------------------------------------
    valis_kwargs: dict = field(default_factory=dict)
    processor_dict: Optional[dict] = None

    def __post_init__(self) -> None:
        """Resolve the default VALIS non-rigid registrar lazily.

        If ``non_rigid_registrar_cls`` was not explicitly supplied, this
        method attempts to import ``OpticalFlowWarper`` from VALIS and use it
        as the default non-rigid registration implementation.

        The import occurs during configuration initialization rather than at
        module import time so that RocqiPath can remain usable when VALIS or
        one of its native dependencies is unavailable.

        If VALIS cannot be imported, the value remains ``None``. The actual
        registration backend is responsible for reporting a missing VALIS
        dependency when VALIS registration is subsequently requested.
        """
        if self.non_rigid_registrar_cls is None:
            try:
                from valis.non_rigid_registrars import OpticalFlowWarper # type: ignore[import]
            except (ImportError, OSError):
                return

            self.non_rigid_registrar_cls = OpticalFlowWarper


@dataclass
class OrbConfig(BaseConfig):
    """Configure RocqiPath's lightweight ORB-based WSI registration backend.

    ``OrbConfig`` controls the contour-assisted ORB registration pipeline used
    by RocqiPath as an alternative to VALIS.

    The ORB backend is intended to provide a comparatively lightweight,
    stain-agnostic registration method that does not require the full VALIS
    dependency stack. It combines tissue-shape information, ORB feature
    matching, affine transformation estimation, optional higher-resolution
    refinement, and normalized cross-correlation validation.

    This backend is particularly useful when:

    - VALIS is unavailable.
    - GPU-backed learned feature matchers are not desired.
    - The slide pair has sufficiently similar tissue geometry.
    - A fast approximate affine registration is sufficient.
    - A lightweight fallback registration method is required.

    Unlike the VALIS backend, which can perform sophisticated rigid and
    deformable/non-rigid registration, the ORB backend primarily estimates an
    affine geometric relationship between the reference and moving images.
    Therefore, it may be less suitable for slides with severe local
    deformation, tearing, stretching, section loss, or major histologic
    differences.

    Parameters
    ----------
    ransac_threshold : float, default=5.0
        RANSAC reprojection-error threshold, in pixels, used when estimating
        the geometric transform from matched ORB features.

        RANSAC identifies a subset of geometrically consistent feature matches
        while rejecting outliers.

        Smaller values enforce stricter geometric agreement and may reject
        valid matches when image correspondence is imperfect.

        Larger values tolerate greater positional disagreement but may allow
        incorrect matches to influence the estimated transformation.

        A value around ``5.0`` pixels is a reasonable default for the
        thumbnail-resolution registration stage.

    orb_thumb_size : int, default=1500
        Maximum thumbnail dimension, in pixels, used for the initial ORB
        registration stage.

        The original whole-slide images are reduced to manageable thumbnail
        representations before contour analysis and ORB feature detection.

        Increasing this value exposes finer tissue structures and may improve
        the initial transformation estimate, but increases memory use and ORB
        feature-detection runtime.

        Decreasing this value accelerates registration but may remove
        diagnostically useful spatial detail.

        This value refers to the processed thumbnail representation and not to
        the original level-0 WSI dimensions.

    orb_refine_thumb_size : int, default=3000
        Maximum thumbnail dimension, in pixels, used for the optional ORB
        refinement stage.

        After an initial affine transformation has been estimated using
        ``orb_thumb_size``, RocqiPath can repeat feature matching at a larger
        image scale to refine that transformation.

        This value is normally larger than ``orb_thumb_size`` because the
        second stage is intended to improve alignment using finer structural
        information.

        For example::

            orb_thumb_size = 1500
            orb_refine_thumb_size = 3000

        performs coarse registration first and then refines the transform at
        approximately twice the linear image dimension.

    orb_refine_enabled : bool, default=True
        Whether to run the higher-resolution ORB refinement stage.

        When ``True``, RocqiPath first estimates an initial registration at
        ``orb_thumb_size`` and subsequently attempts to improve the alignment
        using ``orb_refine_thumb_size``.

        When ``False``, only the initial ORB registration stage is used.

        Disabling refinement can substantially reduce runtime when initial
        alignment quality is already sufficient.

    orb_max_contours : int, default=8
        Maximum number of tissue contours considered when constructing the
        tissue geometry used by the ORB registration pipeline.

        Whole-slide tissue masks can contain multiple disconnected tissue
        fragments, artifacts, labels, or small isolated regions. Restricting
        the number of contours prevents very small or irrelevant structures
        from dominating geometric comparison.

        A larger value allows more disconnected tissue fragments to
        contribute to registration, which may be useful for tissue
        microarrays or fragmented specimens.

        A smaller value focuses registration on the largest tissue regions.

    orb_min_area_frac : float, default=0.001
        Minimum contour area expressed as a fraction of the processed image
        area.

        Contours smaller than this fraction can be excluded from tissue-shape
        analysis.

        For example, ``0.001`` corresponds to approximately 0.1% of the
        processed image area.

        This filter reduces the influence of dust, scanner artifacts, small
        debris, isolated staining artifacts, and other minor connected
        components.

        Increasing this value makes contour filtering more aggressive.
        Decreasing it allows smaller tissue fragments to participate.

        Valid values are normally between ``0`` and ``1``.

    orb_match_threshold : float, default=1.4
        Threshold used by RocqiPath's contour/feature matching logic to
        determine whether candidate tissue structures or ORB registration
        correspondences are sufficiently compatible.

        This is a backend-specific dimensionless threshold rather than a
        physical distance in pixels or micrometres.

        Lower or higher values may make candidate matching more restrictive or
        permissive depending on the exact scoring implementation used by the
        ORB backend.

        The default ``1.4`` is intended to provide a balanced tolerance for
        typical paired histology slides.

        This parameter should generally be tuned only when the ORB backend
        consistently rejects valid slide pairs or accepts geometrically poor
        correspondences.

    min_ncc_threshold : float, default=0.25
        Minimum normalized cross-correlation (NCC) score required for
        registration validation.

        NCC measures similarity between the aligned reference and moving
        image representations after the estimated transformation has been
        applied.

        Values theoretically range approximately from ``-1`` to ``1``:

        - ``1`` indicates very strong positive similarity.
        - ``0`` indicates little linear image similarity.
        - Negative values indicate inverse intensity relationships.

        Histology slides stained with different biomarkers can have
        substantially different pixel intensities even when geometrically
        aligned. Therefore, the default threshold is intentionally modest.

        Increasing this threshold makes registration validation stricter.
        Decreasing it allows more weakly correlated registrations to pass.

        NCC should be interpreted as a registration-quality indicator rather
        than a definitive measure of histologic correspondence.

    Notes
    -----
    ORB registration
        ORB stands for Oriented FAST and Rotated BRIEF. It detects image
        keypoints and represents them using binary descriptors that can be
        matched efficiently between images.

    Affine registration
        The RocqiPath ORB backend primarily estimates a global affine
        transformation. Affine transformations can model translation,
        rotation, scale, and shear, but they cannot model arbitrary local
        tissue deformation.

    Thumbnail coordinates
        ``orb_thumb_size``, ``orb_refine_thumb_size``, and
        ``ransac_threshold`` operate in processed thumbnail coordinate
        systems rather than original level-0 WSI coordinates.

    Cross-stain registration
        ORB is fundamentally an appearance-based feature detector. Therefore,
        highly dissimilar stain pairs may produce fewer reliable ORB feature
        matches than same-stain or structurally similar images.

    VALIS comparison
        Use VALIS when local non-rigid deformation is important or when
        learned cross-image features provide substantially better
        correspondence.

        Use ORB when a lightweight, fast, dependency-minimal affine
        registration approach is sufficient.

    Examples
    --------
    Use the default ORB configuration:

    >>> cfg = OrbConfig()

    Use a larger initial registration thumbnail:

    >>> cfg = OrbConfig(
    ...     orb_thumb_size=2000,
    ...     orb_refine_thumb_size=4000,
    ... )

    Disable the refinement stage:

    >>> cfg = OrbConfig(
    ...     orb_refine_enabled=False,
    ... )

    Use stricter RANSAC filtering:

    >>> cfg = OrbConfig(
    ...     ransac_threshold=3.0,
    ... )

    Ignore smaller tissue fragments:

    >>> cfg = OrbConfig(
    ...     orb_min_area_frac=0.005,
    ...     orb_max_contours=5,
    ... )

    Require stronger post-registration correlation:

    >>> cfg = OrbConfig(
    ...     min_ncc_threshold=0.40,
    ... )
    """

    ransac_threshold: float = 5.0
    orb_thumb_size: int = 1500
    orb_refine_thumb_size: int = 3000
    orb_refine_enabled: bool = True
    orb_max_contours: int = 8
    orb_min_area_frac: float = 0.001
    orb_match_threshold: float = 1.4
    min_ncc_threshold: float = 0.25


__all__ = [
    "AlignmentConfig",
    "OrbConfig",
    "ValisConfig",
]