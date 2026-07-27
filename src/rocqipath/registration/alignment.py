# -*- coding: utf-8 -*-
"""
rocqipath.registration.alignment
========================
Universal toolkit for aligning pairs of whole-slide images (WSI). Each pair
has a fixed ``reference`` slide and a ``moving`` slide that is transformed into
the reference coordinate system. The stains or imaging modalities are not
hard-coded. Registration is performed through VALIS or ORB via
``rocqipath.registration.core``.

──────────────────────────────────────────────────────────────────────────────
Directory layout expected on disk
──────────────────────────────────────────────────────────────────────────────

    <input_dir>/
        <pair_name>/
            <reference_name>/
                <sample_id>_<reference_name>.<ext>
            <moving_name>/
                <sample_id>_<moving_name>.<ext>

``<reference_name>`` and ``<moving_name>`` default to ``reference`` and
``moving`` but may be set to the actual stain labels, e.g.::

    <input_dir>/
        <pair_name>/
            he/
                <sample_id>_he.<ext>
            cd8/
                <sample_id>_cd8.<ext>

via ``AlignmentConfig(reference_name="he", moving_name="cd8")``.

Pair folders are auto-discovered when ``pair_folders`` is ``[]``.
Supported WSI extensions: ``.svs``, ``.tif``, ``.tiff``, ``.ome.tif``,
``.ome.tiff``, ``.ndpi``, ``.scn``, ``.mrxs``, ``.vms``, ``.vmu``.

──────────────────────────────────────────────────────────────────────────────
Output structure
──────────────────────────────────────────────────────────────────────────────

    <output_dir>/
        alignment/
            <sample_id>_<pair_name_lower>/
                aligned_moving.ome.tiff
                grid_map.png
                registration_data.json
                <sample_id>_<pair_name_lower>_center_qc.png  # optional

──────────────────────────────────────────────────────────────────────────────
Filename convention
──────────────────────────────────────────────────────────────────────────────
Filenames are parsed with a **configurable regex** (``filename_pattern``).
When left as ``None`` it is built from ``reference_name``/``moving_name`` and
matches ``<sample_id>_<role>.<ext>``.

The pattern **must** define two named groups:

* ``sample_id`` — shared key used to pair the two slides.
* ``role``      — either ``reference_name`` or ``moving_name`` (case-insensitive).

Example custom pattern::

    # Matches e.g. "PAT-042_reference_stain.tif"
    r"^(?P<sample_id>[A-Z]+-\\d+)_(?P<role>reference|moving)_stain\\.tif$"

──────────────────────────────────────────────────────────────────────────────
Quickstart
──────────────────────────────────────────────────────────────────────────────

    from rocqipath.registration import run_alignment, AlignmentConfig

    results = run_alignment(AlignmentConfig(
        input_dir  = "./data/wsi",
        output_dir = "./data/wsi/aligned",
        # pair_folders=[] → auto-discover every pair folder
    ))

Named stains instead of the generic ``reference``/``moving`` labels::

    results = run_alignment(AlignmentConfig(
        input_dir      = "./data/wsi",
        output_dir     = "./data/wsi/aligned",
        reference_name = "he",
        moving_name    = "cd8",
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
    "build_filename_pattern",
    "discover_pair_folders",
    "list_wsi_files",
    "parse_wsi_filename",
    "index_pair_folder",
    "build_sample_pairs",
    # QC
    "qc_center_patch_side_by_side",
    # Processor
    "AlignmentProcessor",
    # Entry point
    "run_alignment",
]

import os
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from rocqipath.logger import logger
from rocqipath.magnification import DEFAULT_TARGET_MAGNIFICATION
from rocqipath.output import OutputLayout

try:
    from tqdm.auto import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):  # type: ignore[misc]
        """No-op fallback for :func:`tqdm.auto.tqdm` when tqdm isn't installed.

        Returns ``iterable`` unchanged, so any code written as
        ``for x in tqdm(items):`` continues to work identically — just
        without a progress bar — when the optional ``tqdm`` dependency
        is absent.

        Parameters
        ----------
        iterable : Iterable
            The iterable that would normally be wrapped with a progress
            bar.
        *args, **kwargs
            Accepted and ignored, matching tqdm's permissive signature
            (e.g. ``desc=``, ``total=``) so call sites don't need to
            special-case the fallback.

        Returns
        -------
        Iterable
            ``iterable``, unmodified.
        """
        return iterable

try:
    from PIL import Image as _PILImage
    PIL_AVAILABLE = True
except ImportError:
    _PILImage = None
    PIL_AVAILABLE = False


# ── Intro banner — fires once when this module is first imported ──────────────
try:
    from rocqipath.logger import print_banner as _print_banner
    _print_banner()
except Exception:
    pass


# ── Core registration layer ───────────────────────────────────────────────────
try:
    from rocqipath.registration.core import ValisConfig, WSIRegistrar
    WSI_PROCESSING_AVAILABLE = True
except ImportError:
    WSIRegistrar = None      # type: ignore[assignment,misc]
    ValisConfig  = None      # type: ignore[assignment,misc]
    WSI_PROCESSING_AVAILABLE = False
    warnings.warn(
        "rocqipath.registration.core not found. "
        "Set dry_run=True to test slide pairing without running registration.",
        stacklevel=2,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

#: All extensions recognised as WSI files.
WSI_EXTENSIONS: Tuple[str, ...] = (
    ".svs",
    ".tif", ".tiff",
    ".ome.tif", ".ome.tiff",
    ".ndpi", ".scn", ".mrxs",
    ".vms", ".vmu",
)

#: Default label for the fixed/reference slide — used both as the input
#: subfolder name and as the ``role`` token in filenames.
DEFAULT_REFERENCE_NAME: str = "reference"

#: Default label for the moving slide — used both as the input subfolder
#: name and as the ``role`` token in filenames.
DEFAULT_MOVING_NAME: str = "moving"


def build_filename_pattern(
    reference_name: str = DEFAULT_REFERENCE_NAME,
    moving_name:    str = DEFAULT_MOVING_NAME,
) -> str:
    """
    Build the default filename regex for a given pair of role labels.

    The returned pattern matches ``<sample_id>_<role>.<ext>``, where
    ``role`` is either *reference_name* or *moving_name*. Both labels are
    escaped with :func:`re.escape`, so labels containing regex
    metacharacters (e.g. ``"pan-ck"``) are matched literally.

    Parameters
    ----------
    reference_name : str
        Label identifying the fixed/reference slide.
    moving_name : str
        Label identifying the moving slide.

    Returns
    -------
    str
        A regex string with named groups ``sample_id`` and ``role``,
        suitable for :attr:`AlignmentConfig.filename_pattern`.
    """
    return (
        r"^(?P<sample_id>.+?)_"
        rf"(?P<role>{re.escape(reference_name)}|{re.escape(moving_name)})"
        r"(?:\.[^.]+)+$"
    )


#: Default filename regex. Named groups ``sample_id`` and ``role`` are required.
DEFAULT_FILENAME_PATTERN: str = build_filename_pattern()


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
        Root directory containing pair folders (each with
        ``<reference_name>/`` and ``<moving_name>/`` subdirectories).
    output_dir : str
        Root output directory; one subfolder is created per alignment case.
    pair_folders : list[str]
        Explicit list of pair-folder names to process.
        Leave empty (``[]``) to auto-discover every direct subfolder that
        contains a ``<reference_name>/`` or ``<moving_name>/`` subdirectory.
    reference_name : str
        Label for the fixed/reference slide. Used as the input subfolder
        name and as the ``role`` token in filenames. Defaults to
        ``"reference"``; set to the actual stain (e.g. ``"he"``) to read
        from ``<pair_name>/he/`` instead.
    moving_name : str
        Label for the moving slide. Used as the input subfolder name and
        as the ``role`` token in filenames. Defaults to ``"moving"``; set
        to the actual stain (e.g. ``"cd8"``) to read from
        ``<pair_name>/cd8/`` instead.
    filename_pattern : str or None
        Regex with named groups ``sample_id`` and ``role``.
        ``None`` (the default) builds the pattern from ``reference_name``
        and ``moving_name`` via :func:`build_filename_pattern`, matching
        ``<sample_id>_<role>.<ext>``. Supply a string to override the
        convention entirely — in that case ``role`` must still capture a
        value equal to ``reference_name`` or ``moving_name``.
    alignment_method : str
        Registration backend: ``"valis"`` (default) or ``"orb"``.
    aligned_wsi_level : int
        Pyramid level to write for the aligned moving-slide output
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
    max_physical_field_ratio : float or None
        Maximum allowed reference/moving physical canvas ratio at the target
        magnification. Defaults to 2.0. Set ``None`` only for intentionally
        different fields of view.
    qc_enabled : bool
        Save a centre-patch side-by-side PNG per case when ``True``.
    qc_output_dir : str or None
        QC output directory. ``None`` → ``<output_dir>/qc``.
    qc_reference_level : int
        Reference pyramid level that defines the physical QC window size.
    qc_patch_size : int
        QC crop size in pixels (each panel).
    qc_reference_read_level : int
        Pyramid level to read the reference from for QC (0 = highest quality).
    qc_moving_read_level : int
        Pyramid level to read the aligned moving slide from for QC.
    qc_dpi : int
        DPI for the saved QC figure.
    dry_run : bool
        When ``True``, discover and log pairs only; skip all registration.
    """

    # Paths
    input_dir:  str = "./wsi_input"
    output_dir: str = "./wsi_output/aligned"

    # Pair-folder scope
    pair_folders: List[str] = field(default_factory=list)

    # Role labels (input subfolder names + filename role token)
    reference_name: str = DEFAULT_REFERENCE_NAME
    moving_name:    str = DEFAULT_MOVING_NAME

    # Filename parsing
    filename_pattern: Optional[str] = None

    # Registration
    alignment_method:  str = "valis"
    aligned_wsi_level: int = 0

    # Patch / grid (forwarded to WSIRegistrar)
    patch_size:    int = 512
    grid_density:  int = 10
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    reference_source_magnification: Optional[float] = None
    moving_source_magnification: Optional[float] = None

    # VALIS quality gate
    valis_max_error_um: Optional[float] = None
    max_physical_field_ratio: Optional[float] = 2.0

    # QC
    qc_enabled:       bool           = False
    qc_output_dir:    Optional[str]  = None
    qc_reference_level:      int           = 3
    qc_patch_size:           int           = 512
    qc_reference_read_level: int           = 0
    qc_moving_read_level:    int           = 0
    qc_dpi:                  int           = 300

    # Behaviour
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Resolve ``filename_pattern`` and validate it immediately after construction.

        First checks that ``reference_name`` and ``moving_name`` are
        non-empty and distinct (they name two different input
        subdirectories and two different filename role tokens, so equal
        labels would make pairing ambiguous). When ``filename_pattern``
        is ``None`` it is then built from those two labels via
        :func:`build_filename_pattern`.

        The resolved pattern is compiled once (case-insensitively) and
        checked for the two named capture groups the rest of the
        alignment pipeline depends on for pairing files:
        ``sample_id`` (the shared key used to match the two slides)
        and ``role`` (either ``reference_name`` or ``moving_name``).
        Fails fast with a clear message at config
        construction time rather than deep inside file discovery, where
        a regex mistake would otherwise surface as a confusing "no pairs
        found" result.

        Raises
        ------
        ValueError
            If ``reference_name`` or ``moving_name`` is empty, or the two
            are equal (case-insensitively); if the resolved
            ``filename_pattern`` is not a syntactically valid regular
            expression; or if it is valid but does not define both the
            ``sample_id`` and ``role`` named groups.
        """
        # Role labels must be usable as distinct folder names / role tokens
        if not self.reference_name or not self.moving_name:
            raise ValueError(
                "reference_name and moving_name must be non-empty strings."
            )
        if self.reference_name.lower() == self.moving_name.lower():
            raise ValueError(
                "reference_name and moving_name must differ; both were "
                f"{self.reference_name!r}."
            )

        # Derive the default pattern from the role labels when not supplied
        if self.filename_pattern is None:
            self.filename_pattern = build_filename_pattern(
                self.reference_name, self.moving_name
            )

        # Compile once; validate group names
        try:
            compiled = re.compile(self.filename_pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(
                f"filename_pattern is not a valid regex: {e}"
            ) from e
        for group in ("sample_id", "role"):
            if group not in compiled.groupindex:
                raise ValueError(
                    f"filename_pattern must define named group '{group}'. "
                    f"Pattern: {self.filename_pattern!r}"
                )
        if self.target_magnification <= 0:
            raise ValueError("target_magnification must be > 0")
        if self.max_physical_field_ratio is not None and self.max_physical_field_ratio < 1:
            raise ValueError("max_physical_field_ratio must be >= 1 or None")
        for name, value in (
            ("reference_source_magnification", self.reference_source_magnification),
            ("moving_source_magnification", self.moving_source_magnification),
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


def is_wsi_file(filename: str) -> bool:
    """Return ``True`` when *filename* ends with a recognised WSI extension."""
    name = filename.lower()
    return any(name.endswith(ext) for ext in WSI_EXTENSIONS)


def list_wsi_files(directory: Union[str, Path]) -> List[str]:
    """
    Return a sorted list of WSI filenames found directly inside *directory*.

    Parameters
    ----------
    directory : str or Path

    Returns
    -------
    List[str]
        Bare filenames (not full paths).
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        (f.name for f in directory.iterdir()
         if f.is_file() and is_wsi_file(f.name)),
        key=str.lower,
    )


def discover_pair_folders(
    input_dir: Union[str, Path],
    reference_name: str = DEFAULT_REFERENCE_NAME,
    moving_name:    str = DEFAULT_MOVING_NAME,
) -> List[str]:
    """
    Return names of every direct subdirectory of *input_dir* that contains
    at least one ``<reference_name>/`` or ``<moving_name>/`` subdirectory.

    Used for auto-discovery when ``AlignmentConfig.pair_folders`` is
    empty.

    Parameters
    ----------
    input_dir : str or Path
    reference_name : str
        Subfolder name holding the fixed/reference slides.
    moving_name : str
        Subfolder name holding the moving slides.

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
        if (entry / reference_name).is_dir() or (entry / moving_name).is_dir():
            found.append(entry.name)
    return found


# ══════════════════════════════════════════════════════════════════════════════
# Filename parsing
# ══════════════════════════════════════════════════════════════════════════════

def parse_wsi_filename(
    filename: str,
    pattern:  re.Pattern,
) -> Optional[Tuple[str, str]]:
    """
    Parse a WSI filename using *pattern*.

    Parameters
    ----------
    filename : str
        Bare filename (not a full path).
    pattern : re.Pattern
        Compiled regex with named groups ``sample_id`` and ``role``.

    Returns
    -------
    ``(sample_id, role)`` on success, ``None`` when the name does
    not match the pattern.
    """
    match = pattern.match(Path(filename).name)
    if not match:
        return None
    return match.group("sample_id"), match.group("role").lower()


# ══════════════════════════════════════════════════════════════════════════════
# Slide indexing and pairing
# ══════════════════════════════════════════════════════════════════════════════

def index_pair_folder(
    pair_path: Union[str, Path],
    pattern:        re.Pattern,
    reference_name: str = DEFAULT_REFERENCE_NAME,
    moving_name:    str = DEFAULT_MOVING_NAME,
) -> Dict[Tuple[str, str], str]:
    """
    Scan the ``<reference_name>/`` and ``<moving_name>/`` subdirectories of
    *pair_path* and build a ``{(sample_id, role): full_path}`` index.

    Duplicate keys are warned and the first occurrence is kept.

    Parameters
    ----------
    pair_path : str or Path
    pattern : re.Pattern
        Compiled filename regex (named groups ``sample_id``, ``role``).
    reference_name : str
        Subfolder name holding the fixed/reference slides; also the
        ``role`` token expected in those filenames.
    moving_name : str
        Subfolder name holding the moving slides; also the ``role`` token
        expected in those filenames.

    Returns
    -------
    Dict[Tuple[str, str], str]
        Maps ``(sample_id, role)`` → absolute path string, where ``role``
        is always the canonical ``"reference"`` or ``"moving"`` regardless
        of the labels used on disk.
    """
    pair_path = Path(pair_path)
    index: Dict[Tuple[str, str], str] = {}

    for label, role in ((reference_name, "reference"), (moving_name, "moving")):
        subdir = pair_path / label
        if not subdir.is_dir():
            continue
        for fpath in sorted(subdir.iterdir()):
            if not fpath.is_file() or not is_wsi_file(fpath.name):
                continue
            parsed = parse_wsi_filename(fpath.name, pattern)
            if parsed is None:
                logger.warning(f"Filename did not match pattern, skipping: {fpath.name}")
                continue
            sample_id, parsed_role = parsed
            if parsed_role != label.lower():
                logger.warning(
                    f"Role mismatch for {fpath.name}: filename says {parsed_role!r}, "
                    f"but file is inside {label!r}; skipping"
                )
                continue
            key = (sample_id, role)
            if key in index:
                logger.warning(
                    f"Duplicate key {key!r} — keeping first. Ignoring: {fpath}"
                )
            else:
                index[key] = str(fpath)
    return index


def build_sample_pairs(
    index: Dict[Tuple[str, str], str],
) -> List[Tuple[str, str, str]]:
    """
    Match reference and moving slides by ``sample_id``.

    Parameters
    ----------
    index : Dict[Tuple[str, str], str]
        Output of :func:`index_pair_folder`.

    Returns
    -------
    List[Tuple[str, str, str]]
        ``[(sample_id, reference_path, moving_path), …]`` sorted by ``sample_id``.

    Notes
    -----
    Incomplete pairs (reference without moving, or moving without reference) are logged as
    warnings and excluded from the returned list.
    """
    sample_ids   = sorted({sid for (sid, _) in index})
    pairs: List[Tuple[str, str, str]] = []

    for sid in sample_ids:
        reference_path = index.get((sid, "reference"))
        moving_path = index.get((sid, "moving"))

        if reference_path and moving_path:
            pairs.append((sid, reference_path, moving_path))
        else:
            if not reference_path:
                logger.warning(f"{sid}: moving slide found but reference is missing")
            if not moving_path:
                logger.warning(f"{sid}: reference slide found but moving is missing")
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
        img = img.resize(
            (2 * out_size, 2 * out_size), _PILImage.Resampling.BOX
        )
    return img.resize((out_size, out_size), _PILImage.Resampling.LANCZOS)


def _read_hq_center_crop(
    slide:           Any,
    physical_l0_px:  int,
    read_level:      int,
    out_px:          int,
) -> Tuple[Any, int, float]:
    """
    Read a square centre crop from *slide* at *read_level*.

    The physical window is defined in level-0 pixels so both reference and moving slides
    represent the same tissue area.  The result is resampled to
    *out_px × out_px* via the two-step BOX→LANCZOS method.

    Returns
    -------
    (PIL.Image, level_used, downsample_used)
    """
    read_level = max(0, min(int(read_level), slide.level_count - 1))
    ds   = float(slide.level_downsamples[read_level])
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
    reference_path:  str,
    moving_path:     str,
    out_png:         str,
    *,
    reference_level:      int  = 3,
    patch_size:           int  = 512,
    reference_read_level: int  = 0,
    moving_read_level:    int  = 0,
    title:                str  = "",
    dpi:                  int  = 300,
    show:                 bool = False,
) -> str:
    """
    Save a side-by-side centre-patch QC PNG for a registered pair.

    The physical window is defined by *patch_size* pixels at *reference_level*
    on the reference pyramid so both panels show the same tissue area regardless
    of the pyramid structure of the aligned moving file.

    Parameters
    ----------
    reference_path, moving_path : str
        Paths to the reference and aligned moving WSIs (openslide-compatible).
    out_png : str
        Destination PNG path (parent directories are created automatically).
    reference_level : int
        Reference pyramid level that defines the zoom window.
    patch_size : int
        Output size in pixels for each panel.
    reference_read_level, moving_read_level : int
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
        raise RuntimeError(
            "Pillow is required for QC output.  pip install Pillow"
        )
    try:
        import openslide
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(f"Missing QC dependency: {exc}") from exc

    for label, p in (("Reference", reference_path), ("Moving", moving_path)):
        if not Path(p).is_file():
            raise FileNotFoundError(f"{label} file not found: {p}")

    reference_slide = openslide.OpenSlide(str(reference_path))
    moving_slide = openslide.OpenSlide(str(moving_path))
    try:
        resolved_reference_level = min(reference_level, reference_slide.level_count - 1)
        ds_ref = float(reference_slide.level_downsamples[resolved_reference_level])
        physical_l0_px = int(round(patch_size * ds_ref))

        reference_img, reference_read_level_used, reference_ds = _read_hq_center_crop(
            reference_slide, physical_l0_px, reference_read_level, patch_size
        )
        moving_img, moving_read_level_used, moving_ds = _read_hq_center_crop(
            moving_slide, physical_l0_px, moving_read_level, patch_size
        )

        fig, axes = plt.subplots(1, 2, figsize=(12, 6))
        axes[0].imshow(reference_img, interpolation="none")
        axes[0].set_title(
            f"Reference L{resolved_reference_level} (ds={ds_ref:.2f}) | "
            f"read-L{reference_read_level_used} (ds={reference_ds:.2f})\n"
            f"{patch_size} px output from {physical_l0_px} L0 px window"
        )
        axes[0].axis("off")

        axes[1].imshow(moving_img, interpolation="none")
        axes[1].set_title(
            f"Moving read-L{moving_read_level_used} (ds={moving_ds:.2f})\n"
            f"same physical window — {patch_size} px output"
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
        reference_slide.close()
        moving_slide.close()


# ══════════════════════════════════════════════════════════════════════════════
# Data containers
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CaseContext:
    """Metadata bundle for a single reference/moving slide pair."""

    case_id:   str       # e.g. "sample_0001_marker_a"
    sample_id: str       # e.g. "sample_0001"
    pair_name: str       # e.g. "serial_section_01" or "cd8"
    reference_file: str  # absolute path to the fixed/reference WSI
    moving_file: str     # absolute path to the moving WSI
    grids:     List[int] = field(default_factory=list)

    @classmethod
    def from_paths(
        cls,
        reference_path: str,
        moving_path: str,
        pair_name: str,
        *,
        sample_id: Optional[str] = None,
    ) -> "CaseContext":
        """
        Convenience constructor.

        When *sample_id* is omitted it is derived from the reference filename
        stem (everything before the first ``_``).
        """
        if sample_id is None:
            sample_id = Path(reference_path).stem.split("_")[0]
        return cls(
            case_id       = f"{sample_id}_{pair_name.lower()}",
            sample_id     = sample_id,
            pair_name     = pair_name,
            reference_file = str(Path(reference_path).resolve()),
            moving_file    = str(Path(moving_path).resolve()),
        )


@dataclass
class AlignedCaseResult:
    """Outcome of aligning one WSI pair."""

    case:        CaseContext
    registrar:   Any        # WSIRegistrar instance, or None in dry-run
    thumb:       Any        # Grid-map PIL.Image, or None
    valid_grids: List[int]  # Grid indices that passed tissue QC
    aligned_moving_path: Optional[str] = None  # Path to saved OME-TIFF, if any


# ══════════════════════════════════════════════════════════════════════════════
# AlignmentProcessor
# ══════════════════════════════════════════════════════════════════════════════

class AlignmentProcessor:
    """
    Orchestrates slide pairing, registration, and optional QC for all
    pair folders under ``config.input_dir``.

    Parameters
    ----------
    config : AlignmentConfig
        Typed configuration object.  Use :func:`run_alignment` as the
        normal entry point rather than instantiating this class directly.

    Attributes
    ----------
    pair_folders : List[str]
        Pair-folder names that will be processed (after auto-discovery
        if ``config.pair_folders`` is empty).
    """

    def __init__(self, config: AlignmentConfig) -> None:
        """Resolve directories, compile the filename pattern, and discover pair folders.

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
          ``self._pattern`` (already resolved and validated for its
          required named groups by
          :meth:`AlignmentConfig.__post_init__`, so no further
          validation happens here).
        - ``self.pair_folders`` is resolved from
          ``config.pair_folders`` if non-empty, otherwise
          auto-discovered by scanning ``self.input_dir`` via
          :func:`discover_pair_folders`, using
          ``config.reference_name``/``config.moving_name`` as the
          expected subfolder names. If neither yields any folders,
          a warning is logged (not an error — an empty
          ``self.pair_folders`` list means :meth:`run` will simply process
          zero cases).
        """
        self.cfg = config

        self.input_dir  = ensure_directory(config.input_dir,  create=False)
        self.output_dir = ensure_directory(config.output_dir, create=True)

        # Compile filename pattern once
        self._pattern = re.compile(config.filename_pattern, re.IGNORECASE)

        # Resolve pair-folder list
        configured = config.pair_folders or []
        self.pair_folders: List[str] = (
            configured if configured
            else discover_pair_folders(
                self.input_dir, config.reference_name, config.moving_name
            )
        )
        if not self.pair_folders:
            logger.warning(
                "No alignment pair folders found under: %s\n"
                "Each pair folder must have a '%s/' and/or '%s/' subdirectory.",
                self.input_dir,
                config.reference_name,
                config.moving_name,
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
        return ValisConfig(
            max_acceptable_error_um=self.cfg.valis_max_error_um
        )

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
            "patch_size":          self.cfg.patch_size,
            "grid_density":        self.cfg.grid_density,
            "base_output_dir": str(output_root),
            "output_item_name": item_name,
            "target_magnification": self.cfg.target_magnification,
            "reference_source_magnification": self.cfg.reference_source_magnification,
            "moving_source_magnification": self.cfg.moving_source_magnification,
            "max_physical_field_ratio": self.cfg.max_physical_field_ratio,
        }

    # ── per-case alignment ────────────────────────────────────────────────────

    def align_case(
        self,
        case:         CaseContext,
        output_root:  Union[str, Path],
    ) -> AlignedCaseResult:
        """
        Register one reference/moving pair and save the aligned moving WSI.

        Parameters
        ----------
        case : CaseContext
        output_root : str or Path
            Alignment output root; the case subfolder is
            created inside it by ``WSIRegistrar``.

        Returns
        -------
        AlignedCaseResult
            Contains the registrar, grid thumbnail, tissue grid list, and
            path to the saved aligned moving OME-TIFF.
        """
        if self.cfg.dry_run:
            return AlignedCaseResult(
                case=case, registrar=None, thumb=None, valid_grids=[]
            )

        if not WSI_PROCESSING_AVAILABLE:
            raise RuntimeError(
                "rocqipath.registration.core is not installed. "
                "Install the package or set dry_run=True."
            )

        registrar = WSIRegistrar(
            case.reference_file,
            case.moving_file,
            self._make_registrar_cfg(Path(output_root), case.case_id),
            valis_cfg=self._make_valis_config(),
        )

        registrar.register_slides(method=self.cfg.alignment_method)
        thumb, valid_grids = registrar.generate_grid_map()
        aligned_path = registrar.save_aligned_wsi(
            level=self.cfg.aligned_wsi_level,
            output_path=str(Path(registrar.output_dir) / "aligned_moving.ome.tiff"),
        )

        return AlignedCaseResult(
            case             = case,
            registrar        = registrar,
            thumb            = thumb,
            valid_grids      = valid_grids,
            aligned_moving_path = aligned_path,
        )

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> List[AlignedCaseResult]:
        """
        Process every alignment pair folder and return alignment results.

        For each pair folder:
        1. Index the ``<reference_name>/`` and ``<moving_name>/`` subdirectories.
        2. Build reference/moving pairs by ``sample_id``.
        3. Register and save each pair (unless ``dry_run=True``).
        4. Optionally generate a centre-patch QC PNG per case.

        Returns
        -------
        List[AlignedCaseResult]
        """
        all_results: List[AlignedCaseResult] = []
        total_ok = total_fail = 0

        for pair_name in self.pair_folders:
            pair_path = self.input_dir / pair_name
            if not pair_path.is_dir():
                logger.warning(f"Alignment pair folder not found: {pair_path}")
                continue

            module_out = OutputLayout(self.output_dir).module_dir("alignment")
            logger.info(f"Pair folder: {pair_name}  →  {module_out}")

            index = index_pair_folder(
                pair_path,
                self._pattern,
                reference_name = self.cfg.reference_name,
                moving_name    = self.cfg.moving_name,
            )
            pairs = build_sample_pairs(index)

            if not pairs:
                logger.warning(
                    f"No complete {self.cfg.reference_name}/{self.cfg.moving_name} "
                    f"pairs found in {pair_path}"
                )
                continue

            ok = fail = 0

            with tqdm(pairs, desc=f"Aligning {pair_name}", unit="pair") as pbar:
                for sample_id, reference_path, moving_path in pbar:
                    case_id = f"{sample_id}_{pair_name.lower()}"
                    pbar.set_description(f"{pair_name} | {sample_id}")

                    case = CaseContext(
                        case_id       = case_id,
                        sample_id     = sample_id,
                        pair_name     = pair_name,
                        reference_file = reference_path,
                        moving_file    = moving_path,
                    )

                    if self.cfg.dry_run:
                        logger.info(
                            f"[DRY RUN] {case_id}"
                            f"  {self.cfg.reference_name}={reference_path}"
                            f"  {self.cfg.moving_name}={moving_path}"
                        )
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
                                    self.cfg.qc_output_dir
                                    or str(Path(registrar.output_dir))
                                )
                                moving_qc = (
                                    aligned.aligned_moving_path
                                    or case.moving_file
                                )
                                qc_center_patch_side_by_side(
                                    reference_path = case.reference_file,
                                    moving_path    = str(moving_qc),
                                    out_png         = str(
                                        qc_root / f"{case_id}_center_qc.png"
                                    ),
                                    reference_level      = self.cfg.qc_reference_level,
                                    patch_size           = self.cfg.qc_patch_size,
                                    reference_read_level = self.cfg.qc_reference_read_level,
                                    moving_read_level    = self.cfg.qc_moving_read_level,
                                    title                = case_id,
                                    dpi                  = self.cfg.qc_dpi,
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

            total_ok   += ok
            total_fail += fail
            logger.info(f"{pair_name} — ok={ok}  failed={fail}")

        logger.info(
            f"Alignment complete — total ok={total_ok}  failed={total_fail}"
        )
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
    from rocqipath.logger import print_banner
    print_banner()
    return AlignmentProcessor(config).run()