"""
rocqipath.extraction._extraction_engine
===================================
Internal shared primitives for core (multi-region) and whole-slide
extraction pipelines.
Not part of the public API — import from core_extraction or tissue_extraction.
"""

from __future__ import annotations
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

try:
    import pyvips

    _PYVIPS_AVAILABLE = True
except (ImportError, OSError):
    pyvips = None
    _PYVIPS_AVAILABLE = False  # type: ignore[assignment]
from rocqipath.magnification import (
    DEFAULT_TARGET_MAGNIFICATION,
    objective_magnification_from_properties,
)
from rocqipath.logger import add_log_file, logger

for _n in ("pyvips", "VIPS", "PIL", "PIL.Image", "PIL.TiffImagePlugin", "matplotlib", "openslide"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)
SUPPORTED_EXTENSIONS: frozenset = frozenset({".tif", ".tiff", ".svs"})


@dataclass
class _BaseExtractionConfig:
    """Shared fields for whole-slide and TMA extraction.

    Magnification fields are physical objective magnifications, not scanner-
    specific pyramid indexes. ``detection_level`` remains as a deprecated
    escape hatch for older notebooks; leave it as ``None`` for consistent
    scanner-independent behavior.
    """

    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    detection_magnification: float = 1.25
    source_magnification: Optional[float] = None
    detection_level: Optional[int] = None
    preview_scale: float = 0.2
    min_area_fraction: float = 0.0005
    tif_tile: bool = True
    tif_pyramid: bool = True
    tif_compression: str = "lzw"
    tif_quality: int = 99
    skip_existing: bool = True

    def __post_init__(self) -> None:
        """Validate the shared extraction fields immediately after construction.

        Runs automatically after dataclass construction (the standard
        ``__post_init__`` hook) and checks the three fields whose valid
        ranges aren't already enforced by their type alone. Subclasses
        (e.g. ``CoreExtractionConfig``, ``TissueExtractionConfig``) that
        define their own ``__post_init__`` should call
        ``super().__post_init__()`` first so these base checks still run.

        Raises
        ------
        ValueError
            If ``min_area_fraction`` is outside ``[0.0, 1.0]``, if
            ``preview_scale`` is not strictly positive, or if
            ``tif_quality`` is outside ``[1, 100]``.
        """
        if not (0.0 <= self.min_area_fraction <= 1.0):
            raise ValueError(f"min_area_fraction must be in [0, 1]; got {self.min_area_fraction}")
        if self.preview_scale <= 0:
            raise ValueError(f"preview_scale must be > 0; got {self.preview_scale}")
        if not (1 <= self.tif_quality <= 100):
            raise ValueError(f"tif_quality must be in [1, 100]; got {self.tif_quality}")
        if self.target_magnification <= 0:
            raise ValueError("target_magnification must be > 0")
        if self.detection_magnification <= 0:
            raise ValueError("detection_magnification must be > 0")
        if self.detection_magnification > self.target_magnification:
            raise ValueError("detection_magnification cannot exceed target_magnification")
        if self.source_magnification is not None and self.source_magnification <= 0:
            raise ValueError("source_magnification must be > 0 when supplied")
        if self.detection_level is not None and self.detection_level < 0:
            raise ValueError("detection_level must be >= 0 when supplied")


def configure_logging(
    save_dir: Optional[str] = None,
    *,
    file_level: str = "DEBUG",
    log_filename: str = "extraction.log",
) -> None:
    """Attach a persistent loguru file sink inside ``save_dir``, in addition
    to the module-level stderr sink configured at import time.

    Parameters
    ----------
    save_dir : str, optional
        Directory in which to create the log file. Created if it doesn't
        already exist. If ``None`` (the default), this function is a
        no-op — no file sink is added, and logging continues to go only
        to stderr via the sink configured at module import time.
    file_level : str, optional
        Minimum log level written to the file sink (e.g. ``"DEBUG"``,
        ``"INFO"``). Case-insensitive; uppercased internally to match
        loguru's expected level names. Defaults to ``"DEBUG"`` so the
        file captures more detail than typically shown on the console.
    log_filename : str, optional
        Name of the log file created inside ``save_dir``. Defaults to
        ``"extraction.log"``; pipeline modules typically override this
        with a more specific name (e.g. ``"core_extraction.log"``).

    Notes
    -----
    Each call adds a *new* sink via :func:`loguru.logger.add` — calling
    this function multiple times (e.g. once per pipeline run within the
    same process) will accumulate multiple file sinks rather than
    replacing the previous one. The added sink has no rotation
    (``rotation=None``) and writes UTF-8 text with a
    ``"{time} | {level} | {message}"`` format (without the colour tags
    used by the console sink, since log files are typically viewed in a
    plain text editor).
    """
    if save_dir is not None:
        os.makedirs(save_dir, exist_ok=True)
        log_path = str((Path(save_dir) / log_filename).resolve())
        add_log_file(log_path, level=file_level)


def _vips_to_numpy_rgb(img: Any) -> np.ndarray:
    """Convert a pyvips image to a 3-channel RGB ``uint8`` NumPy array.

    Parameters
    ----------
    img : pyvips.Image
        Source image, in any pyvips-supported band configuration
        (grayscale, RGB, RGBA, or with extra bands).

    Returns
    -------
    numpy.ndarray
        A ``(height, width, 3)`` array of dtype ``uint8`` containing only
        the first three (RGB) bands.

    Notes
    -----
    If ``img`` has an alpha channel (``img.hasalpha()``), it is first
    flattened (composited against a background, removing the alpha
    band) via :meth:`pyvips.Image.flatten`. If more than three bands
    remain after that (e.g. multi-channel fluorescence data), only the
    first three are kept via band-slicing (``img[:3]``). The underlying
    pixel buffer is copied into a NumPy array via
    :meth:`pyvips.Image.write_to_memory`, so the returned array owns its
    own memory and is independent of the source pyvips image.
    """
    if img.hasalpha():
        img = img.flatten()
    if img.bands > 3:
        img = img[:3]
    return np.ndarray(
        buffer=img.write_to_memory(), dtype=np.uint8, shape=[img.height, img.width, img.bands]
    )[:, :, :3]


def _vips_properties(img: Any) -> Dict[str, Any]:
    """Return readable libvips metadata without failing on lazy fields."""
    properties: Dict[str, Any] = {}
    for key in img.get_fields():
        try:
            properties[key] = img.get(key)
        except Exception:
            continue
    return properties


def _resolve_vips_magnification(img: Any, fallback: Optional[float]) -> Tuple[float, str]:
    """Resolve a pyvips image's objective magnification and metadata source."""
    return objective_magnification_from_properties(_vips_properties(img), fallback=fallback)


def _open_vips_pyramid_level(path: Path, level: int) -> Any:
    """Open a pyramid level using the first syntax supported by the slide."""
    last_error: Optional[Exception] = None
    for param in (f"[level={level}]", f"[page={level}]"):
        try:
            return pyvips.Image.new_from_file(
                f"{path}{param}", access=pyvips.enums.Access.SEQUENTIAL
            )
        except pyvips.Error as exc:
            last_error = exc
    if level == 0:
        return pyvips.Image.new_from_file(str(path), access="sequential")
    raise last_error or RuntimeError(f"Pyramid level {level} is unavailable")


def _load_thumbnail(
    wsi_path: Path,
    level: Optional[int] = None,
    *,
    target_magnification: float = 1.25,
    source_magnification: Optional[float] = None,
) -> np.ndarray:
    """Load a downsampled thumbnail of a whole-slide image via pyvips.

    Attempts, in order, to open the requested pyramid level using two
    different pyvips access syntaxes (some formats expose pyramid levels
    as ``[level=N]``, others as ``[page=N]``), and falls back to loading
    the full-resolution image and resizing it in-memory if neither
    succeeds.

    Parameters
    ----------
    wsi_path : Path
        Path to the whole-slide image file.
    level : int
        Requested pyramid level, where level 0 is full resolution and
        each subsequent level is (conventionally) half the linear
        resolution of the previous one.

    Returns
    -------
    numpy.ndarray
        The thumbnail as a ``(height, width, 3)`` ``uint8`` RGB array
        (via :func:`_vips_to_numpy_rgb`).

    Raises
    ------
    ImportError
        If the optional ``pyvips`` dependency is not installed.

    Notes
    -----
    Resolution order:

    1. Try ``f"{path}[level={level}]"`` (common for SVS and similar
       formats).
    2. Try ``f"{path}[page={level}]"`` (common for multi-page TIFF-based
       formats).
    3. If both raise :class:`pyvips.Error`, log a warning and fall back
       to opening the full-resolution image and resizing it by
       ``1 / (2 ** level)`` — this is slow (it loads the entire base
       resolution into memory) but guarantees a result for formats whose
       pyramid structure pyvips can't address directly.

    All three paths ultimately return through :func:`_vips_to_numpy_rgb`,
    so the returned array is always RGB-only regardless of the source
    image's band count.
    """
    if not _PYVIPS_AVAILABLE:
        raise ImportError("pyvips is required. pip install rocqipath[extraction]")
    path = Path(wsi_path)
    base = _open_vips_pyramid_level(path, 0)

    # Backward compatibility for callers that explicitly request an index.
    if level is not None:
        try:
            image = _open_vips_pyramid_level(path, level)
        except Exception:
            logger.warning(f"Level {level} unavailable for {path.name}; resizing level 0.")
            image = base.resize(1 / (2**level))
        return _vips_to_numpy_rgb(image)

    base_mag, source = _resolve_vips_magnification(base, source_magnification)
    if target_magnification > base_mag:
        raise ValueError(
            f"Detection magnification {target_magnification:g}x exceeds "
            f"{path.name}'s base magnification {base_mag:g}x"
        )

    candidates = [(0, base)]
    for candidate_level in range(1, 12):
        try:
            candidate = _open_vips_pyramid_level(path, candidate_level)
        except Exception:
            break
        if (
            candidate.width == candidates[-1][1].width
            and candidate.height == candidates[-1][1].height
        ):
            break
        candidates.append((candidate_level, candidate))

    def native_mag(item: Tuple[int, Any]) -> float:
        """Estimate a candidate level's objective magnification from width."""
        return base_mag * (item[1].width / base.width)

    chosen_level, chosen = min(
        candidates, key=lambda item: abs(math.log(native_mag(item) / target_magnification))
    )
    chosen_mag = native_mag((chosen_level, chosen))
    resize = target_magnification / chosen_mag
    if not math.isclose(resize, 1.0, rel_tol=1e-6):
        chosen = chosen.resize(resize)
    logger.debug(
        f"pyvips | {path.name} | objective={base_mag:g}x ({source}) | "
        f"detection={target_magnification:g}x | level={chosen_level} | "
        f"size={chosen.width}x{chosen.height}"
    )
    return _vips_to_numpy_rgb(chosen)


def _resample_region(
    region: Any, *, source_magnification: float, target_magnification: float
) -> Any:
    """Resample a level-0 crop to an exact physical output magnification."""
    if target_magnification > source_magnification:
        raise ValueError(
            f"target_magnification ({target_magnification:g}x) exceeds "
            f"source_magnification ({source_magnification:g}x)"
        )
    scale = target_magnification / source_magnification
    return region if math.isclose(scale, 1.0, rel_tol=1e-6) else region.resize(scale)


def _sort_contours_spatially(contours: List) -> List:
    """Sort OpenCV contours into reading order (top-to-bottom row-by-row,
    left-to-right within each row).

    Useful for numbering detected tissue regions in a consistent,
    human-intuitive order (e.g. region 1 is top-left, region 2 is next
    along that row, etc.) rather than in whatever order
    :func:`cv2.findContours` happened to return them.

    Parameters
    ----------
    contours : list
        A list of OpenCV contours (as returned by
        :func:`cv2.findContours`), each an ``(N, 1, 2)`` array of point
        coordinates.

    Returns
    -------
    list
        The same contours, reordered. Returns an empty list unchanged if
        ``contours`` is empty.

    Notes
    -----
    Algorithm:

    1. Compute each contour's bounding box (via
       :func:`cv2.boundingRect`) and centroid (the bounding box's
       center point).
    2. Compute a row tolerance as half the average bounding-box height
       across all contours — centroids whose vertical distance falls
       within this tolerance of each other are considered to be on the
       same "row".
    3. Sort all contours by centroid Y first, then greedily group
       consecutive contours into rows: a contour joins the current row if
       its centroid Y is within ``row_tol`` of the *last* item added to
       that row (not the row's average), otherwise it starts a new row.
    4. Within each row, sort by centroid X (left to right).
    5. Concatenate the rows in order.

    This is a heuristic, not a rigorous document-layout algorithm — it
    works well for roughly grid-aligned regions (as expected on
    multi-core slides) but can misgroup contours whose centroids sit
    right at a row-tolerance boundary.
    """
    if not contours:
        return []
    boxes = [cv2.boundingRect(c) for c in contours]
    centroids = [(x + w // 2, y + h // 2) for x, y, w, h in boxes]
    avg_h = sum(b[3] for b in boxes) / len(boxes)
    row_tol = avg_h * 0.5
    items = sorted(zip(contours, centroids, boxes), key=lambda i: i[1][1])
    rows: List = []
    current_row = [items[0]]
    for item in items[1:]:
        if abs(item[1][1] - current_row[-1][1][1]) < row_tol:
            current_row.append(item)
        else:
            rows.append(current_row)
            current_row = [item]
    if current_row:
        rows.append(current_row)
    result: List = []
    for row in rows:
        row.sort(key=lambda i: i[1][0])
        result.extend(item[0] for item in row)
    return result


def _detect_regions(
    thumbnail: np.ndarray,
    min_area_fraction: float,
    only_circles: bool = False,
    min_circularity: float = 0.0,
) -> List[Dict[str, float]]:
    """Detect tissue regions on a thumbnail via Otsu thresholding, shared by
    both the core-extraction and tissue-extraction pipelines.

    Parameters
    ----------
    thumbnail : numpy.ndarray
        A ``(height, width, 3)`` RGB thumbnail image (typically from
        :func:`_load_thumbnail`) to detect regions on.
    min_area_fraction : float
        Minimum contour area, as a fraction of the thumbnail's total
        area (``height * width``), for a detected blob to be kept.
        Filters out small debris/artifacts.
    only_circles : bool, optional
        When ``True``, additionally reject contours that fail a
        circularity test (see ``min_circularity``). Used by the core
        (multi-region) extraction pipeline, where regions are expected
        to be roughly circular; left ``False`` for whole-slide tissue
        extraction, where regions can be any shape.
    min_circularity : float, optional
        Minimum circularity score, computed as
        :math:`4\\pi \\cdot \\text{area} / \\text{perimeter}^2` (1.0 for a
        perfect circle, lower for more irregular shapes). Only enforced
        when ``only_circles=True``.

    Returns
    -------
    list of dict
        One dict per detected region, each with keys ``"rx"``, ``"ry"``,
        ``"rw"``, ``"rh"`` — the region's bounding box expressed as
        fractions of the thumbnail's width/height (all in ``[0, 1]``),
        so the result is resolution-independent and can be scaled to any
        pyramid level or the full-resolution slide. Regions are returned
        in reading order (top-to-bottom, left-to-right), via
        :func:`_sort_contours_spatially`.

    Notes
    -----
    Detection pipeline:

    1. Convert ``thumbnail`` to grayscale.
    2. Apply a 13×13 Gaussian blur to suppress noise before
       thresholding.
    3. Apply Otsu's method (inverted binary threshold, so darker
       tissue-like regions become foreground) via
       :func:`cv2.threshold` with ``THRESH_BINARY_INV + THRESH_OTSU``.
    4. Find external contours only (:data:`cv2.RETR_EXTERNAL`) — nested
       contours (holes within a region) are not returned separately.
    5. Filter by ``min_area_fraction`` and, if requested, circularity.
    6. Convert surviving contours to relative bounding boxes and sort
       them spatially.
    """
    h, w = thumbnail.shape[:2]
    gray = cv2.cvtColor(thumbnail, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (13, 13), 0)
    _, thr = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = h * w * min_area_fraction
    valid: List = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        if only_circles:
            peri = cv2.arcLength(cnt, True)
            if peri == 0:
                continue
            if (4 * np.pi * area) / (peri**2) < min_circularity:
                continue
        valid.append(cnt)
    rel_boxes: List[Dict[str, float]] = []
    for cnt in _sort_contours_spatially(valid):
        x, y, bw, bh = cv2.boundingRect(cnt)
        rel_boxes.append({"rx": x / w, "ry": y / h, "rw": bw / w, "rh": bh / h})
    return rel_boxes


def _save_tif(region: Any, tif_path: Path, cfg: _BaseExtractionConfig) -> None:
    """Write a cropped region to disk as a tiled, optionally pyramidal TIFF.

    Parameters
    ----------
    region : pyvips.Image
        The cropped image region to save (typically the output of
        ``full_slide_image.crop(x, y, w, h)``).
    tif_path : Path
        Destination file path. Parent directories are *not* created here
        — callers are expected to have already created ``tif_path``'s
        parent directory.
    cfg : _BaseExtractionConfig
        Supplies the TIFF output options: ``tif_tile`` (tiled layout),
        ``tif_pyramid`` (multi-resolution pyramid), ``tif_compression``
        (codec, e.g. ``"lzw"``), and ``tif_quality`` (compression
        quality, used by lossy codecs).

    Notes
    -----
    Thin wrapper around :meth:`pyvips.Image.tiffsave`; all TIFF-writing
    behaviour is delegated to pyvips/libvips.
    """
    region.tiffsave(
        str(tif_path),
        tile=cfg.tif_tile,
        pyramid=cfg.tif_pyramid,
        compression=cfg.tif_compression,
        Q=cfg.tif_quality,
    )


def _save_preview(region: Any, preview_path: Path, preview_scale: float) -> None:
    """Write a downscaled JPEG preview of a region to disk.

    Parameters
    ----------
    region : pyvips.Image
        The full-resolution cropped region to preview.
    preview_path : Path
        Destination JPEG file path.
    preview_scale : float
        Downscale factor applied before saving, e.g. ``0.2`` for a
        preview at 20% of the region's linear dimensions. Must be
        positive (validated upstream by
        :meth:`_BaseExtractionConfig.__post_init__`).

    Notes
    -----
    Saved at JPEG quality 85 with ``strip=True`` (metadata stripped) via
    :meth:`pyvips.Image.jpegsave` — fixed, not configurable through this
    helper, since previews are for quick visual QC rather than archival
    use.
    """
    region.resize(preview_scale).jpegsave(str(preview_path), Q=85, strip=True)


def _region_outputs_exist(region_dir: Path, tag: str) -> bool:
    """Check whether all three expected output files for a region already exist.

    Used to implement resume/skip-existing behaviour in the extraction
    pipelines: if this returns ``True``, the region has already been
    fully processed and can be safely skipped.

    Parameters
    ----------
    region_dir : Path
        Directory expected to contain the region's output files.
    tag : str
        The region's identifying tag (e.g. ``"region_003"``), used to
        build each expected filename.

    Returns
    -------
    bool
        ``True`` only if all three of ``{tag}.tif``,
        ``{tag}_preview.jpg``, and ``{tag}_manifest.json`` exist inside
        ``region_dir``. ``False`` if any one of them is missing —
        partial output is treated as "not done" so a previously
        interrupted run can safely resume and regenerate the incomplete
        region.
    """
    return all(
        [
            (region_dir / f"{tag}.tif").exists(),
            (region_dir / f"{tag}_preview.jpg").exists(),
            (region_dir / f"{tag}_manifest.json").exists(),
        ]
    )


def _write_region_manifest(
    manifest_path: Path,
    *,
    pipeline: str,
    sample_id: str,
    region_number: int,
    source_file: str,
    rel_box: Dict[str, float],
    abs_box: Dict[str, int],
    full_slide_dims: Dict[str, int],
    detection_source: str,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a single region's JSON manifest describing its provenance and geometry.

    Parameters
    ----------
    manifest_path : Path
        Destination JSON file path (typically alongside the region's
        ``.tif`` and ``_preview.jpg`` — see :func:`_region_outputs_exist`
        for the expected naming convention).
    pipeline : str
        Which extraction pipeline produced this region, e.g. ``"core"``
        or ``"tissue"``. Written verbatim into the manifest.
    sample_id : str
        Identifier of the parent slide/sample this region was extracted
        from.
    region_number : int
        1-based index of this region among all regions extracted from
        the same slide.
    source_file : str
        Filename (not full path) of the source whole-slide image.
    rel_box : dict
        Relative bounding box ``{"rx", "ry", "rw", "rh"}`` with values in
        ``[0, 1]``, expressing the region's location as a fraction of
        the full slide's dimensions (resolution-independent).
    abs_box : dict
        Absolute bounding box ``{"x", "y", "w", "h"}`` in full-resolution
        pixels, corresponding to ``rel_box`` at the slide's base level.
    full_slide_dims : dict
        ``{"width", "height"}`` of the full source slide at base
        resolution, for reference.
    detection_source : str
        How this region's boundary was determined, e.g. ``"otsu"`` for
        automatic thresholding-based detection.
    extra_meta : dict, optional
        Additional key-value pairs to merge into the manifest on top of
        the standard fields (e.g. pipeline-specific metadata). When
        provided, its keys are merged in via ``dict.update`` and will
        overwrite any standard field of the same name.

    Notes
    -----
    Writes UTF-8 JSON with 2-space indentation via :func:`json.dump`. The
    manifest always includes a ``"generated_at"`` UTC timestamp
    (ISO 8601, with a literal ``"Z"`` suffix) recorded at the moment this
    function runs, in addition to ``pipeline``, ``sample_id``,
    ``region_number``, ``source_file``, ``detection_source``, a nested
    ``"coordinates"`` object holding both ``rel_box`` (as
    ``"relative"``) and ``abs_box`` (as ``"absolute_pixels"``), and
    ``full_slide_dims``.
    """
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    m: Dict[str, Any] = {
        "generated_at": generated_at,
        "pipeline": pipeline,
        "sample_id": sample_id,
        "region_number": region_number,
        "source_file": source_file,
        "detection_source": detection_source,
        "coordinates": {"relative": rel_box, "absolute_pixels": abs_box},
        "full_slide_dims": full_slide_dims,
    }
    if extra_meta:
        m.update(extra_meta)
    with open(manifest_path, "w") as fh:
        json.dump(m, fh, indent=2)


def _write_slide_manifest(
    path: Path,
    *,
    pipeline: str,
    sample_id: str,
    source_file: str,
    n_regions: int,
    regions: List[Dict[str, Any]],
) -> None:
    """Write a slide-level JSON manifest summarising every region extracted from it.

    Complements :func:`_write_region_manifest` (one file per region) with
    a single top-level summary per source slide, written once all of
    that slide's regions have been processed.

    Parameters
    ----------
    path : Path
        Destination JSON file path (typically
        ``<slide_dir>/<slide_name>_manifest.json``).
    pipeline : str
        Which extraction pipeline produced these regions, e.g.
        ``"core"`` or ``"tissue"``. Written verbatim into the manifest.
    sample_id : str
        Identifier of the slide these regions were extracted from.
    source_file : str
        Filename (not full path) of the source whole-slide image.
    n_regions : int
        Count of regions that were actually saved (as opposed to
        detected-but-skipped, e.g. via resume/skip-existing logic) —
        callers determine this count themselves before calling this
        function.
    regions : list of dict
        Per-region summary dicts (one per detected region, including
        skipped ones), each typically containing at least a region
        number/tag and a status field — the exact shape is defined by
        the calling pipeline, not validated here.

    Notes
    -----
    Writes UTF-8 JSON with 2-space indentation via :func:`json.dump`. The
    manifest always includes a ``"generated_at"`` UTC timestamp
    (ISO 8601, with a literal ``"Z"`` suffix) recorded at the moment this
    function runs, in addition to ``pipeline``, ``sample_id``,
    ``source_file``, ``n_regions``, and the full ``regions`` list.
    """
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with open(path, "w") as fh:
        json.dump(
            {
                "generated_at": generated_at,
                "pipeline": pipeline,
                "sample_id": sample_id,
                "source_file": source_file,
                "n_regions": n_regions,
                "regions": regions,
            },
            fh,
            indent=2,
        )
