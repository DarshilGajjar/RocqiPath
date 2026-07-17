"""
roqcipath.extraction.core_extraction
=====================================
Multi-region (core) isolation pipeline.

Detects circular tissue regions ("cores") on paired H&E + IHC whole-slide
images and extracts each one as a tiled pyramidal TIFF with a JPEG preview
and a JSON manifest. Suited to any slide layout containing multiple
discrete circular tissue samples — microarrays, biopsy punch collections,
or any other multi-core arrangement — regardless of sample count or which
biomarker(s) are being imaged.

Use this module when a slide contains multiple circular tissue regions.
For a slide containing a single contiguous tissue section, use
roqcipath.extraction.tissue_extraction instead.

Core-specific parameters in CoreExtractionConfig
--------------------------------------------------
- only_circles / min_circularity   — filter out non-circular blobs
- per_stain_detection              — run Otsu independently per stain
- fallback_to_he                   — use H&E boxes when IHC count mismatches
- box_scale                        — expand bounding box by a scale factor
- ihc_enhance / clahe_clip_limit / clahe_tile_size  — CLAHE + DAB boost

None of these apply to single-region whole-slide images.

Quickstart
----------
::

    from roqcipath.extraction import CoreExtractionConfig, run_core_extraction_pipeline

    run_core_extraction_pipeline(
        input_dir     = "./data/cores",
        output_root   = "./data/cores/extracted",
        cfg           = CoreExtractionConfig(
            only_circles    = True,
            min_circularity = 0.60,
            ihc_enhance     = True,
        ),
        target_stains = ["H&E", "marker_A"],
    )
"""

from __future__ import annotations

__all__ = [
    "CoreExtractionConfig",
    "discover_pairs",
    "get_reference_boxes",
    "enhance_ihc_thumbnail",
    "extract_stain_cores",
    "run_core_extraction_pipeline",
]

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from roqcipath.extraction._extraction_engine import (
    SUPPORTED_EXTENSIONS,
    _BaseExtractionConfig,
    _detect_regions,
    _load_thumbnail,
    _region_outputs_exist,
    _resample_region,
    _resolve_vips_magnification,
    _save_preview,
    _save_tif,
    _write_region_manifest,
    _write_slide_manifest,
    configure_logging,
    logger,
)
from roqcipath.output import OutputLayout

try:
    import pyvips; _PYVIPS_AVAILABLE = True
except ImportError:
    pyvips = None; _PYVIPS_AVAILABLE = False  # type: ignore[assignment]

try:
    from roqcipath.logger import console, get_logger as _get_logger
    _log = _get_logger("core_extraction")
except Exception:
    import logging as _sl
    _log = _sl.getLogger("roqcipath.extraction.core_extraction")  # type: ignore[assignment]
    from rich.console import Console as _C
    console = _C(highlight=False)  # type: ignore[assignment]

from rich.panel import Panel
from rich.table import Table

# ── Intro banner — fires once when this module is first imported ──────────────
try:
    from roqcipath.logger import print_banner as _print_banner
    _print_banner()
except Exception:
    pass

_HE_KEYWORDS:  Tuple[str, ...] = ("hne", "h&e", "he")
_IHC_KEYWORDS: Tuple[str, ...] = (
    "cd8","cd31","caix","meca79","cd3","cd56","cd68","cd163","mhc1","pdl1",
)


# ══════════════════════════════════════════════════════════════════════════════
# CoreExtractionConfig
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CoreExtractionConfig(_BaseExtractionConfig):
    """Configuration for multi-region (core) extraction.

    Inherits from _BaseExtractionConfig: detection_level, preview_scale,
    min_area_fraction, tif_* output options, skip_existing.

    Core-specific parameters
    -----------------------
    only_circles : bool
        Reject contours that fail the circularity test.  Should be True
        for genuine multi-core slides.
    min_circularity : float
        Minimum circularity 4pi*area/perimeter^2 in [0, 1].
        Values 0.5-0.7 work well for most tissue cores.
    per_stain_detection : bool
        Run Otsu detection independently on each IHC thumbnail.
    fallback_to_he : bool
        When per-stain Otsu finds a different core count than H&E,
        fall back to H&E boxes to keep counts consistent across stains.
    box_scale : float
        Expand each bounding box symmetrically.  1.0 = exact fit,
        1.3 adds ~15% margin on each side.
    ihc_enhance : bool
        Apply CLAHE + DAB saturation boost before Otsu detection.
        Strongly recommended for DAB-stained IHC slides.
    clahe_clip_limit : float
        CLAHE clip limit.  Typical range 2-10.
    clahe_tile_size : tuple[int, int]
        CLAHE tile grid size.  (8, 8) is a good default.
    """
    # Core-specific
    only_circles:    bool  = True
    min_circularity: float = 0.70

    # Multi-stain registration awareness
    per_stain_detection: bool  = True
    fallback_to_he:      bool  = True
    box_scale:           float = 1.0

    # IHC contrast enhancement
    ihc_enhance:      bool            = True
    clahe_clip_limit: float           = 3.0
    clahe_tile_size:  Tuple[int, int] = field(default_factory=lambda: (8, 8))

    def __post_init__(self) -> None:
        """Validate core-specific fields on top of the shared base validation.

        Calls ``super().__post_init__()`` first (validating
        ``min_area_fraction``, ``preview_scale``, ``tif_quality`` from
        :class:`_BaseExtractionConfig`), then checks the three fields
        specific to core extraction.

        Raises
        ------
        ValueError
            If ``min_circularity`` is outside ``[0.0, 1.0]``, if
            ``box_scale`` is not strictly positive, or if
            ``clahe_clip_limit`` is not strictly positive.
        """
        super().__post_init__()
        if not (0.0 <= self.min_circularity <= 1.0):
            raise ValueError(f"min_circularity must be in [0, 1]; got {self.min_circularity}")
        if self.box_scale <= 0:
            raise ValueError(f"box_scale must be > 0; got {self.box_scale}")
        if self.clahe_clip_limit <= 0:
            raise ValueError(f"clahe_clip_limit must be > 0; got {self.clahe_clip_limit}")


# ══════════════════════════════════════════════════════════════════════════════
# IHC contrast enhancement  (core-specific)
# ══════════════════════════════════════════════════════════════════════════════

def enhance_ihc_thumbnail(rgb: np.ndarray, cfg: CoreExtractionConfig) -> np.ndarray:
    """CLAHE + DAB saturation boost to improve IHC core/background separation.

    1. Convert RGB → LAB, apply CLAHE to L*, convert back.
    2. Boost saturation of brown (DAB) pixels in HSV hue [5°, 22°].

    Parameters
    ----------
    rgb : np.ndarray   uint8 RGB, shape (H, W, 3)
    cfg : CoreExtractionConfig

    Returns
    -------
    np.ndarray   uint8 RGB, same shape
    """
    lab     = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe   = cv2.createCLAHE(clipLimit=cfg.clahe_clip_limit,
                               tileGridSize=cfg.clahe_tile_size)
    enhanced = cv2.cvtColor(cv2.merge([clahe.apply(l), a, b]), cv2.COLOR_LAB2RGB)

    hsv              = cv2.cvtColor(enhanced, cv2.COLOR_RGB2HSV).astype(np.float32)
    h_ch, s_ch, v_ch = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = (h_ch >= 5) & (h_ch <= 22) & (s_ch >= 40) & (v_ch >= 40) & (v_ch <= 220)
    s_ch[mask] = np.clip(s_ch[mask] * 1.5, 0, 255)
    hsv[..., 1] = s_ch
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)


# ══════════════════════════════════════════════════════════════════════════════
# Slide discovery and pairing
# ══════════════════════════════════════════════════════════════════════════════

def _classify_stain(filename: str) -> Optional[Tuple[str, str]]:
    """Classify a filename as H&E or a recognised IHC marker, by keyword match.

    Parameters
    ----------
    filename : str
        The filename to classify (case-insensitive matching).

    Returns
    -------
    tuple of (str, str), or None
        ``("IHC", "<MARKER>")`` if the filename contains one of the
        known IHC keywords in :data:`_IHC_KEYWORDS` (checked first,
        longest keyword first so e.g. ``"cd163"`` matches before the
        shorter ``"cd3"`` would); ``("HE", "HnE")`` if it instead
        contains one of the H&E keywords in :data:`_HE_KEYWORDS`; or
        ``None`` if neither matches.

    Notes
    -----
    This classifier is keyword-based against a fixed list of known IHC
    marker abbreviations (see :data:`_IHC_KEYWORDS`) — a filename whose
    biomarker isn't in that list will not be classified as IHC by this
    function, even though the rest of the core-extraction pipeline
    otherwise accepts an arbitrary ``target_stains`` list. This function
    is used for automatic/best-effort stain detection when explicit
    stain labels aren't otherwise available; callers with biomarkers
    outside the built-in keyword list should not rely on it and should
    instead pass explicit ``target_stains``.
    """
    norm = filename.lower()
    for kw in sorted(_IHC_KEYWORDS, key=len, reverse=True):
        if kw in norm: return ("IHC", kw.upper())
    for kw in _HE_KEYWORDS:
        if kw in norm: return ("HE", "HnE")
    return None

def _extract_sample_id(filename: str, extra_keywords: Tuple[str, ...] = ()) -> str:
    """Strip known H&E/IHC stain keywords out of a filename to recover the sample ID.

    Parameters
    ----------
    filename : str
        The filename to process (only its stem, via
        :meth:`pathlib.Path.stem`, is used — the extension is discarded
        and directory components are ignored).

    Returns
    -------
    str
        The filename stem with every occurrence of a known stain keyword
        (from :data:`_HE_KEYWORDS` and :data:`_IHC_KEYWORDS`, matched
        case-insensitively, longest first) removed, along with its
        surrounding ``-``/``_`` delimiters. Runs of consecutive
        underscores left behind by the removal are collapsed to a single
        underscore, and leading/trailing underscores are stripped.

    Notes
    -----
    Example: ``"Sample_0001_CD8.tif"`` → stem ``"Sample_0001_CD8"`` →
    keyword ``"cd8"`` removed → ``"Sample_0001"``. Like
    :func:`_classify_stain`, this relies on the fixed keyword lists
    :data:`_HE_KEYWORDS` and :data:`_IHC_KEYWORDS`, so a biomarker token
    not in either list will remain in the returned sample ID rather than
    being stripped out.
    """
    stem    = Path(filename).stem
    all_kws = sorted(_HE_KEYWORDS + _IHC_KEYWORDS + extra_keywords, key=len, reverse=True)
    pattern = "|".join(re.escape(kw) for kw in all_kws)
    cleaned = re.sub(rf"[-_]?(?:{pattern})[-_]?", "_", stem, flags=re.IGNORECASE)
    return re.sub(r"_+", "_", cleaned).strip("_")


def discover_pairs(input_dir: str, use_suffix_pairing: bool = False,
                   biomarker: str = "",
                   stain_labels: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Scan input_dir and group WSI files into H&E / IHC pairs by sample ID.

    Parameters
    ----------
    input_dir : str
    use_suffix_pairing : bool
        Use mF1/mE5-style suffix matching instead of keyword matching.
    biomarker : str
        Required when use_suffix_pairing=True.

    Returns
    -------
    dict : { sample_id: { stain_label: {"path": Path, "label": str} } }
    """
    if use_suffix_pairing:
        from roqcipath.utils import find_hne_ihc_pairs_by_suffix, list_wsi_files
        files = list_wsi_files(input_dir)
        raw   = find_hne_ihc_pairs_by_suffix(files, biomarker)
        label = biomarker.upper() or "IHC"
        return {p["suffix"]: {
            "HnE": {"path": Path(input_dir) / p["hne"], "label": "HnE"},
            label: {"path": Path(input_dir) / p["ihc"], "label": label},
        } for p in raw}

    pairs: Dict[str, Dict[str, Any]] = {}
    custom_labels = [
        label for label in (stain_labels or [])
        if label.lower() != "all" and re.sub(r"[^a-z0-9]", "", label.lower()) not in {"he", "hne"}
    ]
    for path in Path(input_dir).rglob("*"):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS: continue
        info = _classify_stain(path.name)
        matched_custom: Optional[str] = None
        if info is None:
            normalized_name = re.sub(r"[^a-z0-9]", "", path.stem.lower())
            for label in sorted(custom_labels, key=len, reverse=True):
                token = re.sub(r"[^a-z0-9]", "", label.lower())
                if token and token in normalized_name:
                    matched_custom = label
                    info = ("IHC", label)
                    break
        if info is None:
            logger.warning(f"Unrecognised stain, skipping: {path.name}"); continue
        extras = (matched_custom,) if matched_custom else ()
        sid = _extract_sample_id(path.name, extras)
        pairs.setdefault(sid, {})[info[1]] = {"path": path, "label": info[1]}
    return pairs


def get_reference_boxes(he_path: Path,
                        cfg: CoreExtractionConfig) -> Tuple[List[Dict[str, float]], np.ndarray]:
    """Detect tissue cores on the H&E reference slide.

    Returns (rel_boxes, thumbnail).
    """
    thumbnail = _load_thumbnail(
        he_path,
        cfg.detection_level,
        target_magnification=cfg.detection_magnification,
        source_magnification=cfg.source_magnification,
    )
    return _detect_regions(thumbnail, min_area_fraction=cfg.min_area_fraction,
                           only_circles=cfg.only_circles,
                           min_circularity=cfg.min_circularity), thumbnail


# ══════════════════════════════════════════════════════════════════════════════
# Per-stain core extraction
# ══════════════════════════════════════════════════════════════════════════════

def extract_stain_cores(wsi_path: Path, stain_label: str, sample_id: str,
    he_rel_boxes: List[Dict[str, float]], stain_out_dir: str,
    cfg: CoreExtractionConfig,
    cached_rgb: Optional[np.ndarray] = None) -> Tuple[int, int, List[Dict[str, Any]]]:
    """Extract and save every core from one stain slide.

    Parameters
    ----------
    wsi_path, stain_label, sample_id : identifiers
    he_rel_boxes : reference boxes from H&E detection
    stain_out_dir : root output dir for this stain
    cfg : CoreExtractionConfig
    cached_rgb : pre-loaded H&E thumbnail (pass for H&E slides, None for IHC)

    Returns
    -------
    (n_saved, n_skipped_existing, core_manifests)
    """
    os.makedirs(stain_out_dir, exist_ok=True)

    # Determine bounding boxes and detection source
    if cached_rgb is not None:
        active_boxes, detection_source = he_rel_boxes, "he_reference"
    elif cfg.per_stain_detection:
        raw = _load_thumbnail(
            wsi_path,
            cfg.detection_level,
            target_magnification=cfg.detection_magnification,
            source_magnification=cfg.source_magnification,
        )
        thumb = enhance_ihc_thumbnail(raw, cfg) if cfg.ihc_enhance else raw
        if cfg.ihc_enhance:
            logger.debug(f"{stain_label} | CLAHE + DAB enhancement applied")
        ihc_boxes = _detect_regions(thumb, cfg.min_area_fraction,
                                    cfg.only_circles, cfg.min_circularity)
        logger.debug(f"{stain_label} | per-stain Otsu → {len(ihc_boxes)} (H&E: {len(he_rel_boxes)})")
        if len(ihc_boxes) == 0:
            logger.warning(f"{stain_label} | 0 cores — {'fallback to H&E' if cfg.fallback_to_he else 'skipping'}")
            active_boxes     = he_rel_boxes if cfg.fallback_to_he else []
            detection_source = "he_fallback" if cfg.fallback_to_he else "otsu_empty"
        elif cfg.fallback_to_he and len(ihc_boxes) != len(he_rel_boxes):
            logger.warning(f"{stain_label} | count mismatch IHC={len(ihc_boxes)} H&E={len(he_rel_boxes)} → fallback")
            active_boxes, detection_source = he_rel_boxes, "he_fallback"
        else:
            active_boxes, detection_source = ihc_boxes, "per_stain_otsu"
    else:
        active_boxes, detection_source = he_rel_boxes, "he_reference"

    full_img       = pyvips.Image.new_from_file(str(wsi_path), access="sequential")
    full_w, full_h = full_img.width, full_img.height
    full_dims      = {"width": full_w, "height": full_h}
    source_mag, mag_source = _resolve_vips_magnification(
        full_img, cfg.source_magnification
    )

    saved = skipped = 0
    manifests: List[Dict[str, Any]] = []

    for idx, box in enumerate(active_boxes):
        n        = idx + 1
        tag      = f"core_{n:03d}"
        core_dir = Path(stain_out_dir)
        core_dir.mkdir(parents=True, exist_ok=True)

        x = int(box["rx"] * full_w);  y = int(box["ry"] * full_h)
        w = int(box["rw"] * full_w);  h = int(box["rh"] * full_h)
        if cfg.box_scale != 1.0:
            cx = x + w // 2;  cy = y + h // 2
            w  = int(w * cfg.box_scale);  h = int(h * cfg.box_scale)
            x  = cx - w // 2;            y = cy - h // 2
        x = max(0, min(x, full_w-1));  y = max(0, min(y, full_h-1))
        w = max(1, min(w, full_w-x));  h = max(1, min(h, full_h-y))
        abs_box: Dict[str, int] = {"x": x, "y": y, "w": w, "h": h}

        if cfg.skip_existing and _region_outputs_exist(core_dir, tag):
            logger.info(f"  SKIPPED  {stain_label}/{tag}"); skipped += 1; status = "skipped_existing"
        else:
            region = _resample_region(
                full_img.crop(x, y, w, h),
                source_magnification=source_mag,
                target_magnification=cfg.target_magnification,
            )
            _save_tif(region, core_dir / f"{tag}.tif", cfg)
            _save_preview(region, core_dir / f"{tag}_preview.jpg", cfg.preview_scale)
            _write_region_manifest(core_dir / f"{tag}_manifest.json",
                pipeline="core", sample_id=sample_id, region_number=n,
                source_file=Path(wsi_path).name, rel_box=box, abs_box=abs_box,
                full_slide_dims=full_dims, detection_source=detection_source,
                extra_meta={"stain": stain_label,
                            "source_magnification": source_mag,
                            "magnification_source": mag_source,
                            "output_magnification": cfg.target_magnification,
                            "config": {k: v for k, v in asdict(cfg).items()
                                       if k not in ("tif_tile","tif_pyramid")}})
            logger.success(f"  SAVED    {stain_label}/{tag}  [{detection_source}]")
            saved += 1; status = "saved"

        manifests.append({"core_number": n, "core_tag": tag,
            "detection_source": detection_source,
            "relative_box": box, "absolute_box": abs_box, "status": status})

    return saved, skipped, manifests


def _print_config_panel(cfg: CoreExtractionConfig, input_dir: str, output_dir: str) -> None:
    """Render a Rich table summarising the resolved run configuration.

    Printed once at the start of :func:`run_core_extraction_pipeline` so
    the operator can see exactly which parameters (including CLI/config
    defaults) will be used before processing begins.

    Parameters
    ----------
    cfg : CoreExtractionConfig
        The configuration whose fields are displayed.
    input_dir : str
        Input directory path, shown as the first row (not part of
        ``cfg`` since it's a pipeline argument rather than a config
        field).
    output_dir : str
        Output directory path, shown as the second row.

    Notes
    -----
    Purely a display/logging side effect — writes to
    :data:`roqcipath.logger.console` (or its local fallback) and returns
    nothing. CLAHE-related rows (``"CLAHE clip"``, ``"CLAHE tile"``) show
    ``"n/a"`` instead of their values when ``cfg.ihc_enhance`` is
    ``False``, since those parameters have no effect in that case.
    """
    tbl = Table(show_header=False, box=None, padding=(0, 2))
    tbl.add_column("Key", style="bold white", no_wrap=True)
    tbl.add_column("Value", style="bright_cyan")
    for k, v in [("Input dir", input_dir), ("Output dir", output_dir),
        ("Detection zoom", f"{cfg.detection_magnification:g}x" if cfg.detection_level is None else f"legacy level {cfg.detection_level}"),
        ("Output zoom", f"{cfg.target_magnification:g}x"),
        ("Min area fraction", f"{cfg.min_area_fraction:.4f}"),
        ("Circles only", str(cfg.only_circles)),
        ("Min circularity", f"{cfg.min_circularity:.2f}"),
        ("Box scale", f"{cfg.box_scale:.2f}"),
        ("Per-stain Otsu", str(cfg.per_stain_detection)),
        ("Fallback to H&E", str(cfg.fallback_to_he)),
        ("IHC enhance", str(cfg.ihc_enhance)),
        ("CLAHE clip", str(cfg.clahe_clip_limit) if cfg.ihc_enhance else "n/a"),
        ("CLAHE tile", str(cfg.clahe_tile_size)  if cfg.ihc_enhance else "n/a"),
        ("TIF compression", cfg.tif_compression),
        ("Skip existing", str(cfg.skip_existing))]:
        tbl.add_row(k, v)
    console.print(Panel(tbl, title="[bold green]Core Extraction[/]", expand=False))


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_core_extraction_pipeline(input_dir: str, output_root: str,
                     cfg: Optional[CoreExtractionConfig] = None,
                     target_stains: Optional[List[str]] = None) -> None:
    """Discover paired H&E/IHC slides and extract tissue cores.

    Parameters
    ----------
    input_dir : str
    output_root : str
    cfg : CoreExtractionConfig or None
    target_stains : list[str] or None   e.g. ["H&E", "marker_A"], or None for all
    """
    if not _PYVIPS_AVAILABLE:
        raise ImportError("pyvips required. pip install roqcipath[extraction]")
    if cfg is None: cfg = CoreExtractionConfig()

    def normalize_label(label: str) -> str:
        """Normalize H&E aliases and remove punctuation for comparisons."""
        token = re.sub(r"[^a-z0-9]", "", label.lower())
        return "he" if token in {"he", "hne"} else token

    target_stains = target_stains or ["all"]
    target_norm = {normalize_label(s) for s in target_stains}
    process_all   = "all" in target_norm

    layout = OutputLayout(output_root)
    module_dir = layout.module_dir("tissue_extraction")
    configure_logging(save_dir=str(module_dir), log_filename="tma_extraction.log")
    _print_config_panel(cfg, input_dir, str(module_dir))

    pairs = discover_pairs(input_dir, stain_labels=target_stains)
    if not pairs: logger.error(f"No WSI files found in {input_dir}"); return

    n = len(pairs)
    logger.info(f"Core extraction pipeline — {n} block(s)")
    if not process_all: logger.info(f"Target stains: {sorted(target_stains)}")

    for i, (sample_id, stains) in enumerate(pairs.items(), 1):
        pfx = f"[{i}/{n}] {sample_id}"
        if "HnE" not in stains: logger.error(f"{pfx} | No H&E — skipping"); continue
        he_boxes, he_thumb = get_reference_boxes(stains["HnE"]["path"], cfg)
        if not he_boxes:
            logger.warning(f"{pfx} | No cores found — adjust min_area_fraction or min_circularity"); continue

        selected = [(lbl, info) for lbl, info in stains.items()
                    if process_all or normalize_label(lbl) in target_norm]
        logger.info(f"{pfx} | {len(he_boxes)} core(s), {len(selected)} stain(s)")

        for lbl, info in selected:
            # One directory per source slide; no sample/stain/core nesting.
            out = str(layout.item_dir("tissue_extraction", info["path"].stem))
            logger.info(f"{pfx} | {lbl}")
            try:
                ns, nsk, mfs = extract_stain_cores(info["path"], lbl, sample_id,
                    he_boxes, out, cfg, cached_rgb=(he_thumb if lbl == "HnE" else None))
                _write_slide_manifest(Path(out) / f"{sample_id}_{lbl}_manifest.json",
                    pipeline="core", sample_id=sample_id,
                    source_file=info["path"].name, n_regions=len(mfs), regions=mfs)
                logger.success(f"{pfx} | {lbl} — {ns} saved, {nsk} skipped")
            except Exception as exc:
                logger.exception(f"{pfx} | {lbl} failed: {exc}")

    logger.success("Core extraction complete.")
