"""Config-driven patch-discovery and extraction workflow."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image
from tqdm.auto import tqdm

from rocqipath.config import PatchExtractionConfig
from rocqipath.core.output import OutputLayout
from rocqipath.core.slide import SlideReader as _SlideReader
from rocqipath.core.tissue import pil_is_tissue as _pil_is_tissue
from rocqipath.utils.discovery import find_aligned_wsi


def _discover_reference_files(he_dir: str, pattern: "re.Pattern") -> List[Tuple[str, str]]:
    """Recursively find reference-channel files matching ``pattern`` under ``he_dir``.

    Parameters
    ----------
    he_dir : str
        Root directory to walk recursively via :func:`os.walk`.
    pattern : re.Pattern
        Compiled regex (case-insensitive) defining a ``sample_id`` named
        group, matched against each filename via :meth:`re.Pattern.match`
        (basename only, not the full path).

    Returns
    -------
    list of tuple of (str, str)
        One ``(sample_id, full_path)`` tuple per matched file, sorted by
        ``sample_id``. Empty if ``he_dir`` doesn't exist or contains no
        matches.
    """
    out: List[Tuple[str, str]] = []
    for root, _dirs, files in os.walk(he_dir):
        for fn in files:
            m = pattern.match(fn)
            if m:
                out.append((m.group("sample_id"), os.path.join(root, fn)))
    return sorted(out, key=lambda x: x[0])


def _find_aligned_target(
    aligned_dir: str, biomarker: str, sample_id: str, reference_name: str
) -> Optional[str]:
    """Locate the aligned target-channel OME-TIFF for a sample and biomarker.

    Parameterised counterpart of
    :meth:`ReversiblePatchExtractor._find_aligned_ihc` — identical
    directory-search and disambiguation logic, just with
    ``reference_name`` substituted for the hardcoded ``"he"`` suffix
    used there.

    Parameters
    ----------
    aligned_dir : str
        Root directory containing aligned target-channel files.
    biomarker : str
        Biomarker subfolder name under ``aligned_dir``.
    sample_id : str
        Sample identifier, as extracted by
        :func:`_discover_reference_files`.
    reference_name : str
        Reference-channel label used to build the expected case
        directory name, ``<sample_id>_<reference_name>``.

    Returns
    -------
    str or None
        Full path to the resolved aligned target file, or ``None`` if
        the expected case directory doesn't exist or contains no
        ``*.ome.tif*`` files.

    Notes
    -----
    If multiple ``*.ome.tif*`` files exist in the case directory,
    disambiguation is attempted by preferring a filename containing (in
    order) the lowercased biomarker name, then ``"ihc"``, then
    ``"aligned"``. If ambiguity remains, the first match alphabetically
    is used as a last resort rather than failing the whole run.
    """
    return find_aligned_wsi(
        aligned_dir,
        biomarker,
        sample_id,
        reference_name,
        priority_keywords=(biomarker.lower(), "ihc", "aligned"),
        sort_mode="lexical",
        resolve=False,
    )


def _patch_is_tissue(image_pil: "Image.Image", tissue_threshold: float) -> bool:
    """Decide whether a patch contains enough tissue to keep.

    Same brightness-based heuristic as
    :meth:`ReversiblePatchExtractor._is_tissue`, factored out as a
    module-level function so it can be used by both the sequential and
    thread-pool code paths in :func:`run_patch_extraction` without
    depending on a class instance.

    Parameters
    ----------
    image_pil : PIL.Image.Image
        The patch to test (any PIL mode; converted to ``"L"`` grayscale
        internally).
    tissue_threshold : float
        Minimum fraction of pixels darker than 235 (out of 255) for the
        patch to count as tissue.

    Returns
    -------
    bool
        ``True`` if the fraction of non-background pixels is at least
        ``tissue_threshold``; ``False`` otherwise.
    """
    return _pil_is_tissue(
        image_pil,
        threshold=tissue_threshold,
        intensity_threshold=235,
    )


def _extract_case_patches(
    case_id: str, reference_path: str, target_path: str, biomarker: str, cfg: PatchExtractionConfig
) -> Dict[str, Any]:
    """Run sliding-window extraction for a single reference/target case.

    Parameters
    ----------
    case_id : str
        Identifier for this case, used in output filenames (typically
        ``f"{sample_id}_{biomarker}"``).
    reference_path : str
        Path to the reference-channel whole-slide file.
    target_path : str
        Path to the aligned target-channel whole-slide file.
    biomarker : str
        Biomarker label for this case, used to build the output
        directory path.
    cfg : PatchExtractionConfig
        Supplies ``patch_size``, ``stride``, ``tissue_threshold``,
        ``reference_name``, ``moving_name``, and ``output_dir``.

    Returns
    -------
    dict
        ``{"case_id": case_id, "status": "processed", "n_patches": int}``.

    Notes
    -----
    Mirrors :meth:`ReversiblePatchExtractor.extract_from_case`'s sliding
    window / tissue-gate / save-and-record-metadata logic, generalized
    to use ``cfg.reference_name``/``cfg.moving_name`` as both the
    output subdirectory names and the metadata keys, instead of the
    hardcoded ``"he"``/``"ihc"``. Reads patches at pyramid level 0 (full
    resolution). Writes one PNG per kept patch for each of the two
    channels, plus a single ``{case_id}_metadata.json`` recording every
    kept patch's coordinates, size, and output paths.

    This function is called both from a sequential loop and from worker
    threads in a :class:`concurrent.futures.ThreadPoolExecutor` (see
    :func:`run_patch_extraction`) — it opens and closes its own
    :class:`_SlideReader` instances rather than sharing any, so it is
    safe to run concurrently for different cases.
    """
    ref_reader = _SlideReader(reference_path)
    target_reader = _SlideReader(target_path)

    try:
        ref_plan = ref_reader.configure_magnification(
            cfg.target_magnification,
            cfg.reference_source_magnification,
        )

        # The aligned image usually uses the reference physical canvas.
        # If no explicit aligned-image magnification is available, infer it
        # from the raw canvas dimensions relative to the reference.
        target_source_magnification = (
            cfg.target_source_magnification
        )

        if target_source_magnification is None:
            ref_raw_w, ref_raw_h = ref_reader.dimensions
            target_raw_w, target_raw_h = target_reader.dimensions

            width_scale = target_raw_w / ref_raw_w
            height_scale = target_raw_h / ref_raw_h

            scale_difference = abs(width_scale - height_scale)

            if scale_difference > cfg.dimension_tolerance:
                raise ValueError(
                    "Cannot infer aligned-image magnification because "
                    "its width and height scales disagree: "
                    f"width_scale={width_scale:.6f}, "
                    f"height_scale={height_scale:.6f}."
                )

            canvas_scale = (width_scale + height_scale) / 2.0

            target_source_magnification = (
                ref_plan.base_magnification * canvas_scale
            )

            print(
                f"[MAG] {case_id}: inferred aligned-image "
                f"base magnification="
                f"{target_source_magnification:.4f}x "
                f"from canvas scale={canvas_scale:.6f}"
            )

        target_plan = target_reader.configure_magnification(
            cfg.target_magnification,
            target_source_magnification,
        )

        print(
            f"[MAG] {case_id}: "
            f"reference={ref_plan.base_magnification:g}x "
            f"-> {ref_plan.target_magnification:g}x "
            f"(level={ref_plan.level}, "
            f"native={ref_plan.native_magnification:g}x, "
            f"resize={ref_plan.resize_factor:.4f}); "
            f"target={target_plan.base_magnification:g}x "
            f"-> {target_plan.target_magnification:g}x "
            f"(level={target_plan.level}, "
            f"native={target_plan.native_magnification:g}x, "
            f"resize={target_plan.resize_factor:.4f})"
        )

        w, h = ref_reader.target_dimensions
        target_w, target_h = target_reader.target_dimensions

        relative_error = max(
            abs(target_w - w) / w,
            abs(target_h - h) / h,
        )
        
        if relative_error > cfg.dimension_tolerance:
            raise ValueError(
                f"Reference and moving slides differ at {cfg.target_magnification:g}x: "
                f"{w}x{h} versus {target_w}x{target_h} "
                f"(tolerance={cfg.dimension_tolerance:.1%})."
            )

        case_dir = OutputLayout(cfg.output_dir).item_dir("patch_extraction", case_id)

        metadata: Dict[str, Any] = {
            "case_id": case_id,
            "dimensions": (w, h),
            "patch_size": cfg.patch_size,
            "stride": cfg.stride,
            "target_magnification": cfg.target_magnification,
            "reference_base_magnification": ref_plan.base_magnification,
            "reference_read_level": ref_plan.level,
            "target_base_magnification": target_plan.base_magnification,
            "target_read_level": target_plan.level,
            "reference_channel": cfg.reference_name,
            "target_channel": cfg.moving_name,
            "extraction_mode": "sliding",
            "patches": [],
        }
        idx = 1
        for y in range(0, h, cfg.stride):
            for x in range(0, w, cfg.stride):
                tw = min(cfg.patch_size, w - x)
                th = min(cfg.patch_size, h - y)
                ref_p = ref_reader.read_at_magnification((x, y), (tw, th)).convert("RGB")

                if _patch_is_tissue(ref_p, cfg.tissue_threshold):
                    pid = f"{idx:06d}"
                    rp = case_dir / f"{case_id}_{cfg.reference_name}_patch_{pid}.png"
                    ref_p.save(rp, compression=None)

                    tgt_p = target_reader.read_at_magnification((x, y), (tw, th)).convert("RGB")
                    tp = case_dir / f"{case_id}_{cfg.moving_name}_patch_{pid}.png"
                    tgt_p.save(tp, compression=None)
                    tgt_p.close()

                    metadata["patches"].append(
                        {
                            "id": pid,
                            "coordinates": (int(x), int(y)),
                            "size": (int(tw), int(th)),
                            f"{cfg.reference_name}_path": str(rp),
                            f"{cfg.moving_name}_path": str(tp),
                        }
                    )
                    idx += 1

                ref_p.close()

        meta_path = case_dir / f"{case_id}_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return {"case_id": case_id, "status": "processed", "n_patches": idx - 1}
    finally:
        ref_reader.close()
        target_reader.close()


def run_patch_extraction(cfg: PatchExtractionConfig) -> Dict[str, Any]:
    """Run the generalized, config-driven sliding-window patch extraction pipeline.

    For every reference-channel file discovered under ``cfg.he_dir``
    (matching ``cfg.reference_pattern``), and for every biomarker in
    ``cfg.biomarker_folders``, attempts to locate the corresponding
    aligned target-channel file under ``cfg.aligned_dir``. Cases without
    a match are recorded as skipped rather than treated as fatal errors,
    since a partially processed/aligned dataset is common. Matched cases
    are extracted via :func:`_extract_case_patches`, either sequentially
    or concurrently depending on ``cfg.max_workers``.

    Parameters
    ----------
    cfg : PatchExtractionConfig
        Fully validated configuration (validation happens in
        :meth:`PatchExtractionConfig.__post_init__` at construction
        time, not here).

    Returns
    -------
    dict
        ``{"processed": int, "skipped": int, "cases": list of dict}``
        where ``"cases"`` contains one entry per attempted case — either
        ``{"case_id", "status": "processed", "n_patches"}`` or
        ``{"case_id", "status": "skipped"|"failed", "reason"}``.

    Notes
    -----
    **Parallelism.** When ``cfg.max_workers > 1``, cases are submitted to
    a :class:`concurrent.futures.ThreadPoolExecutor`. Threads (not
    processes) are used deliberately: each case's work is dominated by
    I/O (OpenSlide region reads, PNG writes) and NumPy/Pillow operations
    that release the GIL, so threads capture most of the available
    concurrency without the pickling overhead and per-worker OpenSlide
    handle duplication that a process pool would require. If your
    workload is instead CPU-bound (e.g. very large patches with heavy
    NumPy post-processing), you may see limited additional speedup past
    a few workers due to the GIL — profile before setting
    ``max_workers`` very high.

    **No global progress bar** is shown for the parallel path (individual
    cases still log their own completion via ``print()``) — this keeps
    the output readable when multiple cases interleave, at the cost of
    the single unified :mod:`tqdm` bar the sequential path provides.
    """
    pattern = re.compile(cfg.reference_pattern, re.IGNORECASE)
    reference_files = _discover_reference_files(cfg.he_dir, pattern)

    if not reference_files:
        print(
            f"[ERROR] No reference-channel files found under {cfg.he_dir} "
            f"matching pattern: {cfg.reference_pattern}"
        )
        return {"processed": 0, "skipped": 0, "cases": []}

    print(
        f"[INFO] Found {len(reference_files)} reference file(s); "
        f"checking {len(cfg.biomarker_folders)} biomarker(s) each.\n"
    )

    to_process: List[Tuple[str, str, str, str]] = []
    results: List[Dict[str, Any]] = []

    for sample_id, ref_path in reference_files:
        for biomarker in cfg.biomarker_folders:
            case_id = f"{sample_id}_{biomarker}"
            target_path = _find_aligned_target(
                cfg.aligned_dir, biomarker, sample_id, cfg.reference_name
            )
            if target_path is None:
                print(f"[SKIP] {case_id}: aligned target not found")
                results.append(
                    {"case_id": case_id, "status": "skipped", "reason": "aligned target not found"}
                )
                continue
            to_process.append((case_id, ref_path, target_path, biomarker))

    if cfg.max_workers > 1 and len(to_process) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
            futures = {
                pool.submit(
                    _extract_case_patches, case_id, ref_path, target_path, biomarker, cfg
                ): case_id
                for case_id, ref_path, target_path, biomarker in to_process
            }
            for future in concurrent.futures.as_completed(futures):
                case_id = futures[future]
                try:
                    result = future.result()
                    print(f"[OK] {result['case_id']}: {result['n_patches']} patches saved")
                    results.append(result)
                except Exception as e:
                    print(f"[ERROR] {case_id}: {e}")
                    results.append({"case_id": case_id, "status": "failed", "reason": str(e)})
    else:
        for case_id, ref_path, target_path, biomarker in tqdm(
            to_process, desc="Processing Cases", unit="case"
        ):
            try:
                result = _extract_case_patches(case_id, ref_path, target_path, biomarker, cfg)
                tqdm.write(f"[OK] {result['case_id']}: {result['n_patches']} patches saved")
                results.append(result)
            except Exception as e:
                tqdm.write(f"[ERROR] {case_id}: {e}")
                results.append({"case_id": case_id, "status": "failed", "reason": str(e)})

    processed = sum(1 for r in results if r["status"] == "processed")
    skipped = sum(1 for r in results if r["status"] in ("skipped", "failed"))
    print(f"\n[DONE] Processed: {processed}  |  Skipped/Failed: {skipped}")

    return {"processed": processed, "skipped": skipped, "cases": results}
