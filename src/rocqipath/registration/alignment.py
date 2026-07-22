# -*- coding: utf-8 -*-
"""
rocqipath.registration.alignment
========================
Universal toolkit for aligning whole-slide images (WSI) prior to biomarker
analysis.  Pairs H&E slides with IHC/biomarker slides and performs image
registration via VALIS or ORB (via ``rocqipath.registration.core``).

──────────────────────────────────────────────────────────────────────────────
Directory layout expected on disk
──────────────────────────────────────────────────────────────────────────────

    <input_dir>/
        <biomarker>/          ← any biomarker/marker label your dataset uses
            he/
                <sample_id>_he.<ext>
            ihc/
                <sample_id>_<biomarker>.<ext>

Biomarker subfolders are auto-discovered when ``biomarker_folders`` is ``[]``.
Supported WSI extensions: ``.svs``, ``.tif``, ``.tiff``, ``.ome.tif``,
``.ome.tiff``, ``.ndpi``, ``.scn``, ``.mrxs``, ``.vms``, ``.vmu``.

──────────────────────────────────────────────────────────────────────────────
Output structure
──────────────────────────────────────────────────────────────────────────────

    <output_dir>/
        <biomarker>/
            <sample_id>_<biomarker_lower>/
                aligned_ihc.ome.tiff
                grid_map.png
                registration_data.json
        qc/                              ← only when qc_enabled=True
            <sample_id>_<biomarker_lower>_center_qc.png

──────────────────────────────────────────────────────────────────────────────
Filename convention
──────────────────────────────────────────────────────────────────────────────
Filenames are parsed with a **configurable regex** (``filename_pattern``).
The default matches ``<sample_id>_<marker>.<ext>``.

The pattern **must** define two named groups:

* ``sample_id`` — shared key used to pair H&E with IHC slides.
* ``marker``    — stain token (case-insensitive; ``HE`` marks the H&E slide).

Example custom pattern::

    # Matches e.g. "PAT-042_CD3_stain.tif"
    r"^(?P<sample_id>[A-Z]+-\\d+)_(?P<marker>he|cd3|cd8|ki67)_stain\\.tif$"

──────────────────────────────────────────────────────────────────────────────
Quickstart
──────────────────────────────────────────────────────────────────────────────

    from rocqipath.registration import run_alignment, AlignmentConfig

    results = run_alignment(AlignmentConfig(
        input_dir  = "./data/wsi",
        output_dir = "./data/wsi/aligned",
        # biomarker_folders=[] → auto-discover every subfolder
    ))

Dry run (pairing check only, no registration)::

    results = run_alignment(AlignmentConfig(
        input_dir  = "./data/wsi",
        output_dir = "./data/wsi/aligned",
        dry_run    = True,
    ))

──────────────────────────────────────────────────────────────────────────────
Integration notes
──────────────────────────────────────────────────────────────────────────────
* Fully integrated into the ``rocqipath`` package; zero standalone script
  dependencies.
* Logging is unified with the ``rocqipath.registration.alignment`` child logger.
* ``ValisConfig`` and ``WSIRegistrar`` are consumed directly from
  ``rocqipath.registration.core`` — no duplication.
* ``AlignmentConfig`` is a typed dataclass; construct it directly rather than
  passing a raw dict.
"""

from __future__ import annotations

__all__ = [
    # Config
    "AlignmentConfig",
    # Data containers
    "CaseContext",
    "AlignedCaseResult",
    # Discovery helpers (importable utilities)
    "discover_biomarker_folders",
    "list_wsi_files",
    "parse_wsi_filename",
    "index_biomarker_folder",
    "build_sample_pairs",
    # QC
    "qc_center_patch_side_by_side",
    # Processor
    "AlignmentProcessor",
    # Entry point
    "run_alignment",
]

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from rocqipath.logger import logger
from rocqipath.magnification import DEFAULT_TARGET_MAGNIFICATION
from rocqipath.output import OutputLayout
from rocqipath.utils import is_wsi_file, list_wsi_files

try:
    from tqdm.auto import tqdm
except (ImportError, OSError):

    class _NoOpProgress:
        """Small context-manager/iterator replacement for optional tqdm."""

        def __init__(self, iterable):
            self.iterable = iterable

        def __iter__(self):
            return iter(self.iterable)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def set_description(self, *_args, **_kwargs):
            return None

        def set_postfix(self, *_args, **_kwargs):
            return None

        def update(self, *_args, **_kwargs):
            return None

    def tqdm(iterable, *args, **kwargs):  # type: ignore[misc]
        """Return a no-op progress wrapper when tqdm is unavailable."""
        return _NoOpProgress(iterable)


try:
    from PIL import Image as _PILImage

    PIL_AVAILABLE = True
except ImportError:
    _PILImage = None
    PIL_AVAILABLE = False


# ── Core registration layer ───────────────────────────────────────────────────
try:
    from rocqipath.registration.core import ValisConfig, WSIRegistrar

    WSI_PROCESSING_AVAILABLE = True
except ImportError:
    WSIRegistrar = None  # type: ignore[assignment,misc]
    ValisConfig = None  # type: ignore[assignment,misc]
    WSI_PROCESSING_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

#: Default filename regex. Named groups ``sample_id`` and ``marker`` required.
DEFAULT_FILENAME_PATTERN: str = r"^(?P<sample_id>.+?)_(?P<marker>he|[a-z0-9]+)(?:\.[^.]+)+$"


# ══════════════════════════════════════════════════════════════════════════════
# AlignmentConfig — typed configuration container
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class AlignmentConfig:
    """
    Typed configuration for the WSI alignment pipeline.

    All fields have sensible defaults; override only what you need.

    Parameters
    ----------
    input_dir : str
        Root directory containing biomarker subfolders (each with ``he/``
        and ``ihc/`` sub-subdirectories).
    output_dir : str
        Root output directory; one subfolder is created per biomarker.
    biomarker_folders : list[str]
        Explicit list of biomarker subfolder names to process.
        Leave empty (``[]``) to auto-discover every direct subfolder that
        contains an ``he/`` or ``ihc/`` subdirectory.
    filename_pattern : str
        Regex with named groups ``sample_id`` and ``marker``.
        The default matches ``<sample_id>_<marker>.<ext>``.
    alignment_method : str
        Registration backend: ``"valis"`` (default) or ``"orb"``.
    aligned_wsi_level : int
        Pyramid level to write for the aligned IHC output
        (0 = full resolution).
    patch_size : int
        Patch edge length forwarded to ``WSIRegistrar``.
    grid_density : int
        Grid rows / columns forwarded to ``WSIRegistrar``.
    target_magnification : float
        Physical objective magnification for reference and moving patch reads.
        Defaults to 20x and is resolved independently for each slide pyramid.
    valis_max_error_um : float or None
        Maximum acceptable VALIS registration error in µm.
        ``None`` → log the value but do not fail the case.
    qc_enabled : bool
        Save a centre-patch side-by-side PNG per case when ``True``.
    qc_output_dir : str or None
        QC output directory. ``None`` → ``<output_dir>/qc``.
    qc_he_level_ref : int
        H&E pyramid level that defines the physical QC window size.
    qc_patch_size : int
        QC crop size in pixels (each panel).
    qc_he_read_level : int
        Pyramid level to read H&E from for QC (0 = highest quality).
    qc_ihc_read_level : int
        Pyramid level to read IHC from for QC.
    qc_dpi : int
        DPI for the saved QC figure.
    dry_run : bool
        When ``True``, discover and log pairs only; skip all registration.
    """

    # Paths
    input_dir: str = "./wsi_input"
    output_dir: str = "./wsi_output/aligned"

    # Biomarker scope
    biomarker_folders: List[str] = field(default_factory=list)

    # Filename parsing
    filename_pattern: str = DEFAULT_FILENAME_PATTERN

    # Registration
    alignment_method: str = "valis"
    aligned_wsi_level: int = 0

    # Patch / grid (forwarded to WSIRegistrar)
    patch_size: int = 512
    grid_density: int = 10
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    reference_source_magnification: Optional[float] = None
    target_source_magnification: Optional[float] = None

    # VALIS quality gate
    valis_max_error_um: Optional[float] = None

    # QC
    qc_enabled: bool = False
    qc_output_dir: Optional[str] = None
    qc_he_level_ref: int = 3
    qc_patch_size: int = 512
    qc_he_read_level: int = 0
    qc_ihc_read_level: int = 0
    qc_dpi: int = 300

    # Behaviour
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Validate ``filename_pattern`` immediately after construction.

        Compiles ``self.filename_pattern`` once (case-insensitively) and
        checks that it defines the two named capture groups the rest of
        the alignment pipeline depends on for pairing files:
        ``sample_id`` (the shared key used to match H&E with IHC slides)
        and ``marker`` (the stain/biomarker token, with ``"he"`` marking
        the H&E slide). Fails fast with a clear message at config
        construction time rather than deep inside file discovery, where
        a regex mistake would otherwise surface as a confusing "no pairs
        found" result.

        Raises
        ------
        ValueError
            If ``filename_pattern`` is not a syntactically valid regular
            expression, or if it is valid but does not define both the
            ``sample_id`` and ``marker`` named groups.
        """
        # Compile once; validate group names
        try:
            compiled = re.compile(self.filename_pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"filename_pattern is not a valid regex: {e}") from e
        for group in ("sample_id", "marker"):
            if group not in compiled.groupindex:
                raise ValueError(
                    f"filename_pattern must define named group '{group}'. "
                    f"Pattern: {self.filename_pattern!r}"
                )
        if self.target_magnification <= 0:
            raise ValueError("target_magnification must be > 0")
        for name, value in (
            ("reference_source_magnification", self.reference_source_magnification),
            ("target_source_magnification", self.target_source_magnification),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be > 0 when supplied")


# ══════════════════════════════════════════════════════════════════════════════
# Filesystem utilities
# ══════════════════════════════════════════════════════════════════════════════


def ensure_directory(
    path: Union[str, Path],
    *,
    create: bool = True,
) -> Path:
    """
    Resolve *path* to an absolute ``Path``, optionally creating it.

    Parameters
    ----------
    path   : str or Path
    create : bool
        Create missing parent directories when ``True`` (default).

    Raises
    ------
    FileNotFoundError
        When the directory does not exist and ``create=False``.
    """
    path = Path(path).resolve()
    if not path.is_dir():
        if create:
            path.mkdir(parents=True, exist_ok=True)
        else:
            raise FileNotFoundError(f"Directory not found: {path}")
    return path


def discover_biomarker_folders(input_dir: Union[str, Path]) -> List[str]:
    """
    Return names of every direct subdirectory of *input_dir* that contains
    at least one ``he/`` or ``ihc/`` sub-subdirectory.

    Used for auto-discovery when ``AlignmentConfig.biomarker_folders`` is
    empty.

    Parameters
    ----------
    input_dir : str or Path

    Returns
    -------
    List[str]
        Sorted list of subdirectory names.
    """
    input_dir = Path(input_dir)
    found: List[str] = []
    for entry in sorted(input_dir.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "he").is_dir() or (entry / "ihc").is_dir():
            found.append(entry.name)
    return found


# ══════════════════════════════════════════════════════════════════════════════
# Filename parsing
# ══════════════════════════════════════════════════════════════════════════════


def parse_wsi_filename(
    filename: str,
    pattern: re.Pattern,
) -> Optional[Tuple[str, str]]:
    """
    Parse a WSI filename using *pattern*.

    Parameters
    ----------
    filename : str
        Bare filename (not a full path).
    pattern : re.Pattern
        Compiled regex with named groups ``sample_id`` and ``marker``.

    Returns
    -------
    ``(sample_id, marker_upper)`` on success, ``None`` when the name does
    not match the pattern.
    """
    match = pattern.match(Path(filename).name)
    if not match:
        return None
    return match.group("sample_id"), match.group("marker").upper()


# ══════════════════════════════════════════════════════════════════════════════
# Slide indexing and pairing
# ══════════════════════════════════════════════════════════════════════════════


def index_biomarker_folder(
    biomarker_path: Union[str, Path],
    pattern: re.Pattern,
) -> Dict[Tuple[str, str], str]:
    """
    Scan the ``he/`` and ``ihc/`` subdirectories of *biomarker_path* and
    build a ``{(sample_id, marker_upper): full_path}`` index.

    Duplicate keys are warned and the first occurrence is kept.

    Parameters
    ----------
    biomarker_path : str or Path
    pattern : re.Pattern
        Compiled filename regex (named groups ``sample_id``, ``marker``).

    Returns
    -------
    Dict[Tuple[str, str], str]
        Maps ``(sample_id, MARKER)`` → absolute path string.
    """
    biomarker_path = Path(biomarker_path)
    index: Dict[Tuple[str, str], str] = {}

    for subdir_name in ("he", "ihc"):
        subdir = biomarker_path / subdir_name
        if not subdir.is_dir():
            continue
        for fpath in sorted(subdir.iterdir()):
            if not fpath.is_file() or not is_wsi_file(fpath.name):
                continue
            parsed = parse_wsi_filename(fpath.name, pattern)
            if parsed is None:
                logger.warning(f"Filename did not match pattern, skipping: {fpath.name}")
                continue
            sample_id, marker = parsed
            key = (sample_id, marker)
            if key in index:
                logger.warning(f"Duplicate key {key!r} — keeping first. Ignoring: {fpath}")
            else:
                index[key] = str(fpath)
    return index


def build_sample_pairs(
    index: Dict[Tuple[str, str], str],
    biomarker: str,
) -> List[Tuple[str, str, str]]:
    """
    Match H&E slides with biomarker slides by ``sample_id``.

    Parameters
    ----------
    index : Dict[Tuple[str, str], str]
        Output of :func:`index_biomarker_folder`.
    biomarker : str
        Marker token to match against (e.g. ``"marker_A"``).

    Returns
    -------
    List[Tuple[str, str, str]]
        ``[(sample_id, he_path, ihc_path), …]`` sorted by ``sample_id``.

    Notes
    -----
    Incomplete pairs (H&E without IHC, or IHC without H&E) are logged as
    warnings and excluded from the returned list.
    """
    marker_upper = biomarker.upper()
    sample_ids = sorted({sid for (sid, _) in index})
    pairs: List[Tuple[str, str, str]] = []

    for sid in sample_ids:
        he_path = index.get((sid, "HE"))
        marker_path = index.get((sid, marker_upper))

        if he_path and marker_path:
            pairs.append((sid, he_path, marker_path))
        else:
            if not he_path:
                logger.warning(f"{sid}: {marker_upper} found but H&E is missing")
            if not marker_path:
                logger.warning(f"{sid}: H&E found but {marker_upper} is missing")
    return pairs


# ══════════════════════════════════════════════════════════════════════════════
# QC — centre-patch side-by-side image
# ══════════════════════════════════════════════════════════════════════════════


def _resize_twostep(img: Any, out_size: int) -> Any:
    """BOX → LANCZOS two-pass downsample to minimise aliasing."""
    if img.size == (out_size, out_size):
        return img
    w, h = img.size
    if w > 2 * out_size and h > 2 * out_size:
        img = img.resize((2 * out_size, 2 * out_size), _PILImage.Resampling.BOX)
    return img.resize((out_size, out_size), _PILImage.Resampling.LANCZOS)


def _read_hq_center_crop(
    slide: Any,
    physical_l0_px: int,
    read_level: int,
    out_px: int,
) -> Tuple[Any, int, float]:
    """
    Read a square centre crop from *slide* at *read_level*.

    The physical window is defined in level-0 pixels so both H&E and IHC
    represent the same tissue area.  The result is resampled to
    *out_px × out_px* via the two-step BOX→LANCZOS method.

    Returns
    -------
    (PIL.Image, level_used, downsample_used)
    """
    read_level = max(0, min(int(read_level), slide.level_count - 1))
    ds = float(slide.level_downsamples[read_level])
    w0, h0 = slide.level_dimensions[0]
    cx0, cy0 = w0 // 2, h0 // 2
    half = physical_l0_px // 2

    x0 = max(0, cx0 - half)
    y0 = max(0, cy0 - half)

    wl, hl = slide.level_dimensions[read_level]
    req = max(1, int(round(physical_l0_px / ds)))
    req_w = min(req, max(1, wl - int(x0 / ds)))
    req_h = min(req, max(1, hl - int(y0 / ds)))

    img = slide.read_region((x0, y0), read_level, (req_w, req_h)).convert("RGB")
    return _resize_twostep(img, out_px), read_level, ds


def qc_center_patch_side_by_side(
    he_path: str,
    ihc_path: str,
    out_png: str,
    *,
    he_level_ref: int = 3,
    patch_size: int = 512,
    he_read_level: int = 0,
    ihc_read_level: int = 0,
    title: str = "",
    dpi: int = 300,
    show: bool = False,
) -> str:
    """
    Save a side-by-side centre-patch QC PNG for a registered pair.

    The physical window is defined by *patch_size* pixels at *he_level_ref*
    on the H&E pyramid so both panels show the same tissue area regardless
    of the pyramid structure of the aligned IHC file.

    Parameters
    ----------
    he_path, ihc_path : str
        Paths to H&E and aligned IHC WSIs (openslide-compatible).
    out_png : str
        Destination PNG path (parent directories are created automatically).
    he_level_ref : int
        H&E pyramid level that defines the zoom window (e.g. 3 ≈ 20×).
    patch_size : int
        Output size in pixels for each panel.
    he_read_level, ihc_read_level : int
        Pyramid level to *read* from (0 = maximum quality).
    title : str
        Optional ``suptitle`` on the figure.
    dpi : int
        Figure DPI.
    show : bool
        Call ``plt.show()`` after saving.

    Returns
    -------
    str
        Absolute path to the saved PNG.

    Raises
    ------
    RuntimeError
        When Pillow, openslide, or matplotlib are not installed.
    FileNotFoundError
        When either WSI path does not exist.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for QC output.  pip install Pillow")
    try:
        import openslide
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(f"Missing QC dependency: {exc}") from exc

    for label, p in (("H&E", he_path), ("IHC", ihc_path)):
        if not Path(p).is_file():
            raise FileNotFoundError(f"{label} file not found: {p}")

    he_slide = openslide.OpenSlide(str(he_path))
    ihc_slide = openslide.OpenSlide(str(ihc_path))
    try:
        he_ref = min(he_level_ref, he_slide.level_count - 1)
        ds_ref = float(he_slide.level_downsamples[he_ref])
        physical_l0_px = int(round(patch_size * ds_ref))

        he_img, he_lvl, he_ds = _read_hq_center_crop(
            he_slide, physical_l0_px, he_read_level, patch_size
        )
        ihc_img, ihc_lvl, ihc_ds = _read_hq_center_crop(
            ihc_slide, physical_l0_px, ihc_read_level, patch_size
        )

        fig, axes = plt.subplots(1, 2, figsize=(12, 6))
        axes[0].imshow(he_img, interpolation="none")
        axes[0].set_title(
            f"H&E  ref-L{he_ref} (ds={ds_ref:.2f}) | read-L{he_lvl}\n"
            f"{patch_size} px output from {physical_l0_px} L0 px window"
        )
        axes[0].axis("off")

        axes[1].imshow(ihc_img, interpolation="none")
        axes[1].set_title(
            f"IHC  read-L{ihc_lvl} (ds={ihc_ds:.2f})\nsame physical window — {patch_size} px output"
        )
        axes[1].axis("off")

        if title:
            fig.suptitle(title, fontsize=14, fontweight="bold")

        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_png, dpi=dpi, bbox_inches="tight")
        if show:
            plt.show()
        plt.close(fig)

        logger.info(f"[QC] Saved: {out_png}")
        return str(Path(out_png).resolve())
    finally:
        he_slide.close()
        ihc_slide.close()


# ══════════════════════════════════════════════════════════════════════════════
# Data containers
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class CaseContext:
    """Metadata bundle for a single H&E / IHC slide pair."""

    case_id: str  # e.g. "sample_0001_marker_a"
    sample_id: str  # e.g. "sample_0001"
    biomarker: str  # e.g. "marker_A"
    hne_file: str  # absolute path to H&E WSI
    ihc_file: str  # absolute path to IHC WSI
    grids: List[int] = field(default_factory=list)

    @classmethod
    def from_paths(
        cls,
        hne_path: str,
        ihc_path: str,
        biomarker: str,
        *,
        sample_id: Optional[str] = None,
    ) -> "CaseContext":
        """
        Convenience constructor.

        When *sample_id* is omitted it is derived from the H&E filename
        stem (everything before the first ``_``).
        """
        if sample_id is None:
            sample_id = Path(hne_path).stem.split("_")[0]
        return cls(
            case_id=f"{sample_id}_{biomarker.lower()}",
            sample_id=sample_id,
            biomarker=biomarker,
            hne_file=str(Path(hne_path).resolve()),
            ihc_file=str(Path(ihc_path).resolve()),
        )


@dataclass
class AlignedCaseResult:
    """Outcome of aligning one WSI pair."""

    case: CaseContext
    registrar: Any  # WSIRegistrar instance, or None in dry-run
    thumb: Any  # Grid-map PIL.Image, or None
    valid_grids: List[int]  # Grid indices that passed tissue QC
    aligned_ihc_path: Optional[str] = None  # Path to saved OME-TIFF, if any


# ══════════════════════════════════════════════════════════════════════════════
# AlignmentProcessor
# ══════════════════════════════════════════════════════════════════════════════


class AlignmentProcessor:
    """
    Orchestrates slide pairing, registration, and optional QC for all
    biomarker subfolders under ``config.input_dir``.

    Parameters
    ----------
    config : AlignmentConfig
        Typed configuration object.  Use :func:`run_alignment` as the
        normal entry point rather than instantiating this class directly.

    Attributes
    ----------
    biomarkers : List[str]
        Biomarker subfolder names that will be processed (after auto-discovery
        if ``config.biomarker_folders`` is empty).
    """

    def __init__(self, config: AlignmentConfig) -> None:
        """Resolve directories, compile the filename pattern, and discover biomarkers.

        Parameters
        ----------
        config : AlignmentConfig
            Typed configuration object — see the class docstring above.
            Stored on ``self.cfg`` for later use by :meth:`align_case`
            and :meth:`run`.

        Notes
        -----
        Construction performs real filesystem work, not just attribute
        assignment:

        - ``config.input_dir`` is resolved via :func:`ensure_directory`
          with ``create=False`` — it must already exist, or this raises
          :class:`FileNotFoundError`.
        - ``config.output_dir`` is resolved via :func:`ensure_directory`
          with ``create=True`` — it is created if missing.
        - ``config.filename_pattern`` is compiled once into
          ``self._pattern`` (already validated for its required named
          groups by :meth:`AlignmentConfig.__post_init__`, so no further
          validation happens here).
        - ``self.biomarkers`` is resolved from
          ``config.biomarker_folders`` if non-empty, otherwise
          auto-discovered by scanning ``self.input_dir`` via
          :func:`discover_biomarker_folders`. If neither yields any
          folders, a warning is logged (not an error — an empty
          ``self.biomarkers`` list means :meth:`run` will simply process
          zero cases).
        """
        self.cfg = config

        self.input_dir = ensure_directory(config.input_dir, create=False)
        self.output_dir = ensure_directory(config.output_dir, create=True)

        # Compile filename pattern once
        self._pattern = re.compile(config.filename_pattern, re.IGNORECASE)

        # Resolve biomarker list
        configured = config.biomarker_folders or []
        self.biomarkers: List[str] = (
            configured if configured else discover_biomarker_folders(self.input_dir)
        )
        if not self.biomarkers:
            logger.warning(
                "No biomarker subfolders found under: {}. "
                "Each biomarker must have an 'he/' and/or 'ihc/' subdirectory.",
                self.input_dir,
            )

    # ── internal helpers ──────────────────────────────────────────────────────

    def _make_valis_config(self) -> Any:
        """Build a ``ValisConfig`` from this processor's ``AlignmentConfig``.

        Currently forwards only ``valis_max_error_um`` — the rest of
        ``ValisConfig``'s fields are left at their library defaults. Used
        internally by :meth:`align_case` when constructing each
        :class:`~rocqipath.registration.core.WSIRegistrar`.

        Returns
        -------
        ValisConfig
            A config instance with ``max_acceptable_error_um`` set from
            ``self.cfg.valis_max_error_um``.

        Raises
        ------
        RuntimeError
            If :mod:`rocqipath.registration.core` (and therefore VALIS)
            is not installed. Callers should either install the
            ``valis``/``wsi`` extra or set ``dry_run=True`` on the
            ``AlignmentConfig`` to skip real registration entirely.
        """
        if not WSI_PROCESSING_AVAILABLE:
            raise RuntimeError(
                "rocqipath.registration.core is not installed. "
                "Install the package or set dry_run=True."
            )
        return ValisConfig(max_acceptable_error_um=self.cfg.valis_max_error_um)

    def _make_registrar_cfg(self, output_root: Path, item_name: str) -> dict:
        """Build the plain-dict config expected by ``WSIRegistrar``'s constructor.

        Parameters
        ----------
        output_root : Path
            User-selected root beneath which the alignment module directory is created.
        item_name : str
            Per-case folder name beneath ``alignment``.

        Returns
        -------
        dict
            A dict with keys ``"patch_size"``, ``"grid_density"``,
            ``"base_output_dir"`` (as a string), and
            physical magnification fields populated from ``self.cfg``. See
            :class:`~rocqipath.registration.core.WSIRegistrar` for the
            full set of keys it accepts — this helper supplies only the
            subset ``AlignmentConfig`` exposes.
        """
        return {
            "patch_size": self.cfg.patch_size,
            "grid_density": self.cfg.grid_density,
            "base_output_dir": str(output_root),
            "output_item_name": item_name,
            "target_magnification": self.cfg.target_magnification,
            "reference_source_magnification": self.cfg.reference_source_magnification,
            "target_source_magnification": self.cfg.target_source_magnification,
        }

    # ── per-case alignment ────────────────────────────────────────────────────

    def align_case(
        self,
        case: CaseContext,
        output_root: Union[str, Path],
    ) -> AlignedCaseResult:
        """
        Register one H&E / IHC pair and save the aligned IHC WSI.

        Parameters
        ----------
        case : CaseContext
        output_root : str or Path
            Biomarker-level output directory; the case subfolder is
            created inside it by ``WSIRegistrar``.

        Returns
        -------
        AlignedCaseResult
            Contains the registrar, grid thumbnail, tissue grid list, and
            path to the saved aligned IHC OME-TIFF.
        """
        if self.cfg.dry_run:
            return AlignedCaseResult(case=case, registrar=None, thumb=None, valid_grids=[])

        if not WSI_PROCESSING_AVAILABLE:
            raise RuntimeError(
                "rocqipath.registration.core is not installed. "
                "Install the package or set dry_run=True."
            )

        registrar = WSIRegistrar(
            case.hne_file,
            case.ihc_file,
            self._make_registrar_cfg(Path(output_root), case.case_id),
            valis_cfg=self._make_valis_config(),
        )

        registrar.register_slides(method=self.cfg.alignment_method)
        thumb, valid_grids = registrar.generate_grid_map()
        aligned_path = registrar.save_aligned_wsi(level=self.cfg.aligned_wsi_level)

        return AlignedCaseResult(
            case=case,
            registrar=registrar,
            thumb=thumb,
            valid_grids=valid_grids,
            aligned_ihc_path=aligned_path,
        )

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> List[AlignedCaseResult]:
        """
        Process every biomarker subfolder and return alignment results.

        For each biomarker:
        1. Index the ``he/`` and ``ihc/`` sub-subdirectories.
        2. Build H&E / IHC pairs by ``sample_id``.
        3. Register and save each pair (unless ``dry_run=True``).
        4. Optionally generate a centre-patch QC PNG per case.

        Returns
        -------
        List[AlignedCaseResult]
        """
        all_results: List[AlignedCaseResult] = []
        total_ok = total_fail = 0

        for biomarker in self.biomarkers:
            biomarker_path = self.input_dir / biomarker
            if not biomarker_path.is_dir():
                logger.warning(f"Biomarker subfolder not found: {biomarker_path}")
                continue

            module_out = OutputLayout(self.output_dir).module_dir("alignment")
            logger.info(f"Biomarker: {biomarker}  →  {module_out}")

            index = index_biomarker_folder(biomarker_path, self._pattern)
            pairs = build_sample_pairs(index, biomarker)

            if not pairs:
                logger.warning(f"No complete H&E / {biomarker} pairs found in {biomarker_path}")
                continue

            ok = fail = 0

            with tqdm(pairs, desc=f"Aligning {biomarker}", unit="pair") as pbar:
                for sample_id, he_path, marker_path in pbar:
                    case_id = f"{sample_id}_{biomarker.lower()}"
                    pbar.set_description(f"{biomarker} | {sample_id}")

                    case = CaseContext(
                        case_id=case_id,
                        sample_id=sample_id,
                        biomarker=biomarker,
                        hne_file=he_path,
                        ihc_file=marker_path,
                    )

                    if self.cfg.dry_run:
                        logger.info("[DRY RUN] {} HE={} IHC={}", case_id, he_path, marker_path)
                        all_results.append(self.align_case(case, self.output_dir))
                        ok += 1
                        continue

                    registrar = None
                    try:
                        pbar.set_postfix(status="registering")
                        aligned = self.align_case(case, self.output_dir)
                        registrar = aligned.registrar
                        all_results.append(aligned)
                        ok += 1
                        logger.info(f"[OK] {case_id}")

                        # Optional QC
                        if self.cfg.qc_enabled and registrar is not None:
                            try:
                                pbar.set_postfix(status="qc")
                                qc_root = Path(
                                    self.cfg.qc_output_dir or str(Path(registrar.output_dir))
                                )
                                ihc_qc = aligned.aligned_ihc_path or case.ihc_file
                                qc_center_patch_side_by_side(
                                    he_path=case.hne_file,
                                    ihc_path=str(ihc_qc),
                                    out_png=str(qc_root / f"{case_id}_center_qc.png"),
                                    he_level_ref=self.cfg.qc_he_level_ref,
                                    patch_size=self.cfg.qc_patch_size,
                                    he_read_level=self.cfg.qc_he_read_level,
                                    ihc_read_level=self.cfg.qc_ihc_read_level,
                                    title=case_id,
                                    dpi=self.cfg.qc_dpi,
                                )
                            except Exception as qc_err:
                                logger.warning(f"[QC WARN] {case_id}: {qc_err}")

                    except Exception as exc:
                        logger.error(f"[FAIL] {case_id}: {exc}")
                        fail += 1
                    finally:
                        if registrar is not None:
                            try:
                                registrar.close()
                            except Exception:
                                pass
                        pbar.set_postfix(status="done")

            total_ok += ok
            total_fail += fail
            logger.info(f"{biomarker} — ok={ok}  failed={fail}")

        logger.info(f"Alignment complete — total ok={total_ok}  failed={total_fail}")
        return all_results


# ══════════════════════════════════════════════════════════════════════════════
# Public entry points
# ══════════════════════════════════════════════════════════════════════════════


def run_alignment(config: AlignmentConfig) -> List[AlignedCaseResult]:
    """
    Run the full alignment pipeline from a typed ``AlignmentConfig``.

    This is the **primary entry point** for programmatic use:

        from rocqipath.registration import run_alignment, AlignmentConfig

        results = run_alignment(AlignmentConfig(
            input_dir  = "./data/wsi",
            output_dir = "./data/wsi/aligned",
        ))

    Parameters
    ----------
    config : AlignmentConfig

    Returns
    -------
    List[AlignedCaseResult]
    """
    if not WSI_PROCESSING_AVAILABLE and not config.dry_run:
        raise ImportError(
            "WSI registration dependencies are unavailable. Install "
            "'rocqipath[valis]' or set dry_run=True to validate slide pairing."
        )
    return AlignmentProcessor(config).run()
