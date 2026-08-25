"""Orchestrate multi-marker IHC overlay processing for cases and batches."""

from __future__ import annotations

import concurrent.futures
import os
import random
from typing import Any, Dict, List, Optional, Union

import numpy as np
from PIL import Image

from rocqipath.config import IHCOverlayConfig, MarkerProfile, OverlayCombo
from rocqipath.core.exceptions import ExtractionError
from rocqipath.core.output import OutputLayout
from rocqipath.visualization.overlay_figures import (
    _save_composite_figure,
    _save_grid_figure,
)
from rocqipath.visualization.overlay_masks import _build_composite, _marker_mask

__all__ = [
    "MarkerProfile",
    "OverlayCombo",
    "IHCOverlayConfig",
    "process_ihc_overlay",
]

_IMAGE_EXTENSIONS = (".png", ".tif", ".tiff", ".jpg", ".jpeg")


def _resolve_marker_dir(case_dir: str, marker_key: str) -> Optional[str]:
    """Find the subfolder of ``case_dir`` matching ``marker_key`` case-insensitively.

    Parameters
    ----------
    case_dir : str
        Directory expected to contain one subfolder per marker.
    marker_key : str
        Marker key to look for (matched case-insensitively against
        subfolder names, e.g. key ``"pdgfeb"`` matches an on-disk folder
        literally named ``"PDGFEB"``, ``"pdgfeb"``, or any other casing).

    Returns
    -------
    str or None
        Full path to the matched subfolder, or ``None`` if ``case_dir``
        doesn't exist or contains no subfolder matching ``marker_key``.
    """
    if not os.path.isdir(case_dir):
        return None
    for name in os.listdir(case_dir):
        full = os.path.join(case_dir, name)
        if name.lower() == marker_key.lower() and os.path.isdir(full):
            return full
    return None


def _looks_like_case_dir(path: str, marker_keys: List[str]) -> bool:
    """Decide whether ``path`` directly contains at least one recognised marker subfolder.

    Used by :func:`process_ihc_overlay` to distinguish a single case
    directory from a parent directory containing multiple cases.

    Parameters
    ----------
    path : str
        Directory to inspect.
    marker_keys : list of str
        Marker keys to check for (matched case-insensitively).

    Returns
    -------
    bool
        ``True`` if ``path`` exists and at least one of its immediate
        subdirectories matches one of ``marker_keys`` (case-insensitive);
        ``False`` otherwise.
    """
    if not os.path.isdir(path):
        return False
    existing = {n.lower() for n in os.listdir(path) if os.path.isdir(os.path.join(path, n))}
    return any(k.lower() in existing for k in marker_keys)


def _process_single_case(case_id: str, case_dir: str, cfg: IHCOverlayConfig) -> Dict[str, Any]:
    """Generate overlay figures for every patch in one case directory.

    Parameters
    ----------
    case_id : str
        Identifier for this case, used to name the output subdirectory
        (``cfg.save_dir/<case_id>/``).
    case_dir : str
        Directory containing one subfolder per marker (see the module
        docstring's "Expected data structure" section).
    cfg : IHCOverlayConfig
        Full configuration — markers, combinations, rendering and output
        options.

    Returns
    -------
    dict
        ``{"patches_processed": int, "figures_saved": int}``. Both are
        ``0`` if any required marker subfolder is missing, or if no
        patch filename is common to every required marker subfolder —
        in either case a warning is printed and the case is skipped
        rather than raising, since a partially organised dataset (a case
        missing one marker) is common.

    Notes
    -----
    Only the markers actually referenced by ``cfg.combinations`` (the
    union of every combination's ``base`` and ``overlays``) are
    resolved and loaded — markers present in ``cfg.markers`` but not
    used by any combination are ignored for this run. Patches are
    matched across marker subfolders by exact filename (not just stem —
    the extension must match too); only filenames present in *every*
    required marker's subfolder are processed. When
    ``cfg.patches_per_case > 0``, the matched filename list is randomly
    subsampled (via :func:`random.sample`) before processing.
    """
    needed_markers = sorted(
        {key for combo in cfg.combinations for key in [combo.base, *combo.overlays]}
    )

    marker_dirs: Dict[str, str] = {}
    for mk in needed_markers:
        d = _resolve_marker_dir(case_dir, mk)
        if d is None:
            print(f"[WARN] {case_id}: marker folder for '{mk}' not found — skipping case.")
            return {"patches_processed": 0, "figures_saved": 0}
        marker_dirs[mk] = d

    file_sets = [
        {f for f in os.listdir(d) if f.lower().endswith(_IMAGE_EXTENSIONS)}
        for d in marker_dirs.values()
    ]
    common = sorted(set.intersection(*file_sets)) if file_sets else []

    if not common:
        print(f"[WARN] {case_id}: no matching patch filenames across marker folders.")
        return {"patches_processed": 0, "figures_saved": 0}

    if cfg.patches_per_case and cfg.patches_per_case < len(common):
        common = sorted(random.sample(common, cfg.patches_per_case))

    case_save_dir = str(OutputLayout(cfg.save_dir).item_dir("visualization", case_id))

    patches_processed = 0
    figures_saved = 0

    for fname in common:
        stem = os.path.splitext(fname)[0]
        images = {
            mk: np.array(Image.open(os.path.join(marker_dirs[mk], fname)).convert("RGB"))
            for mk in needed_markers
        }
        masks = {mk: _marker_mask(images[mk], cfg.markers[mk]) for mk in needed_markers}
        patches_processed += 1

        for combo in cfg.combinations:
            combo_name = f"{combo.base}_" + "_".join(combo.overlays)
            out_composite = os.path.join(case_save_dir, f"{stem}_{combo_name}_composite.png")
            out_grid = os.path.join(case_save_dir, f"{stem}_{combo_name}_grid.png")

            need_composite = cfg.plot_mode in ("composite", "both")
            need_grid = cfg.plot_mode in ("grid", "both")

            if cfg.skip_existing:
                need_composite = need_composite and not os.path.exists(out_composite)
                need_grid = need_grid and not os.path.exists(out_grid)
                if not need_composite and not need_grid:
                    continue

            composite = _build_composite(images, masks, combo, cfg)

            if need_composite:
                _save_composite_figure(composite, out_composite, cfg)
                figures_saved += 1

            if need_grid:
                _save_grid_figure(images, masks, composite, combo, cfg, out_grid)
                figures_saved += 1

    return {"patches_processed": patches_processed, "figures_saved": figures_saved}


def process_ihc_overlay(
    data_in: str,
    cfg: IHCOverlayConfig,
    mode: str = "patch_dir",
) -> Union[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Generate multi-marker overlay figures for a single case or a batch of cases.

    Auto-detects which situation ``data_in`` represents: if it directly
    contains at least one recognised marker subfolder (see
    :func:`_looks_like_case_dir`), it's treated as a single case;
    otherwise, every immediate subdirectory of ``data_in`` that itself
    looks like a case directory is processed as a separate case.

    Parameters
    ----------
    data_in : str
        Either a single case directory, or a parent directory containing
        multiple case subdirectories.
    cfg : IHCOverlayConfig
        Full configuration — markers, combinations, rendering and output
        options.
    mode : str, optional
        Accepted for interface clarity/future extension but currently
        does not change behaviour — auto-detection (single case vs.
        batch) happens the same way regardless of this argument's value.
        Defaults to ``"patch_dir"``.

    Returns
    -------
    dict
        For a single case: ``{"patches_processed": int, "figures_saved": int}``.

        For a batch: ``{case_id: {"patches_processed": int, "figures_saved": int}, ...}``
        — one entry per processed case subdirectory, keyed by directory
        name.

    Raises
    ------
    ExtractionError
        If ``data_in`` is not itself a recognised single-case directory,
        and none of its immediate subdirectories look like case
        directories either — i.e. nothing processable was found at all.

    Notes
    -----
    **Parallelism.** In batch mode, when ``cfg.max_workers > 1`` and more
    than one case directory was found, cases are processed concurrently
    via a :class:`concurrent.futures.ThreadPoolExecutor` (same threads-
    over-processes rationale as
    :func:`rocqipath.extraction.patch_pipeline.run_patch_extraction`:
    the work is I/O- and NumPy-bound, which releases the GIL, so threads
    capture most of the available concurrency without process-pool
    pickling overhead). With ``max_workers=1`` (the default) or only one
    case, processing is sequential.
    """
    marker_keys = list(cfg.markers.keys())

    if _looks_like_case_dir(data_in, marker_keys):
        case_id = os.path.basename(os.path.normpath(data_in))
        return _process_single_case(case_id, data_in, cfg)

    if not os.path.isdir(data_in):
        raise ExtractionError(f"data_in does not exist: {data_in}")

    case_dirs = [
        (d, os.path.join(data_in, d))
        for d in sorted(os.listdir(data_in))
        if _looks_like_case_dir(os.path.join(data_in, d), marker_keys)
    ]
    if not case_dirs:
        raise ExtractionError(
            f"No case directories with recognisable marker subfolders "
            f"({marker_keys}) found under: {data_in}"
        )

    results: Dict[str, Dict[str, Any]] = {}

    if cfg.max_workers > 1 and len(case_dirs) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
            futures = {
                pool.submit(_process_single_case, cid, cdir, cfg): cid for cid, cdir in case_dirs
            }
            for future in concurrent.futures.as_completed(futures):
                cid = futures[future]
                results[cid] = future.result()
    else:
        for cid, cdir in case_dirs:
            results[cid] = _process_single_case(cid, cdir, cfg)

    return results
