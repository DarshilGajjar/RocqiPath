"""Batch training and application workflows for stain normalization."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import cv2 as cv
import numpy as np

from rocqipath.config import StainNormalizationConfig
from rocqipath.core.console import (
    print_banner,
    print_counts,
    print_done,
    print_error,
    print_info,
    print_section,
    print_step,
    print_summary_table,
    print_warn,
    track,
)
from rocqipath.core.exceptions import ExtractionError
from rocqipath.core.output import OutputLayout
from rocqipath.stain.normalizers import ReinhardNormalizer, get_normalizer, tissue_fraction
from rocqipath.utils.discovery import discover_files
from rocqipath.utils.imageio import imread_rgb, imwrite_rgb


def run_stain_normalization_train(
    input_dir: str,
    output_dir: str,
    cfg: Optional[StainNormalizationConfig] = None,
) -> Path:
    """Fit a normaliser on tissue patches under *input_dir* and save its weights.

    Parameters
    ----------
    input_dir : str
    output_dir : str
        Weights are written to ``<output_dir>/<cfg.n_type>_weights.npz``
        unless ``cfg.weights_path`` is set.
    cfg : StainNormalizationConfig or None

    Returns
    -------
    pathlib.Path
        Path to the saved weights file.
    """
    if cfg is None:
        cfg = StainNormalizationConfig()

    files = discover_files(input_dir, cfg.stains)
    normalizer = get_normalizer(cfg.n_type)
    module_dir = OutputLayout(output_dir).module_dir("stain_normalization")
    weights = (
        Path(cfg.weights_path) if cfg.weights_path else module_dir / f"{cfg.n_type}_weights.npz"
    )
    is_reinhard = isinstance(normalizer, ReinhardNormalizer)

    print_banner()

    if not files:
        print_error(f"No patches found in '{input_dir}' for stains {cfg.stains}. Aborting.")
        raise ExtractionError(f"No patches found in '{input_dir}' for stains {cfg.stains}")

    print_section("Training")
    print_summary_table(
        [
            ("Algorithm", cfg.n_type.upper()),
            ("Input dir", input_dir),
            ("Stains", ", ".join(cfg.stains)),
            ("Total files", len(files)),
            (
                "Strategy",
                "incremental stats"
                if is_reinhard
                else f"mosaic  (max {cfg.max_train_patches} patches)",
            ),
            ("Min tissue", f"{cfg.fit_min_tissue:.0%}"),
            ("Weights out", str(weights)),
        ],
        title="Train Config",
    )

    # ── Phase 1: collect tissue patches ────────────────────────────────────
    print_step("SCAN", f"Sampling tissue patches (min tissue ≥ {cfg.fit_min_tissue:.0%}) …")
    picked: List[np.ndarray] = []
    for fp in track(files, "Scanning patches"):
        img = imread_rgb(fp)
        if img is not None and tissue_fraction(img) >= cfg.fit_min_tissue:
            picked.append(cv.resize(img, (256, 256)))

    if not picked:
        print_error("No tissue patches passed the tissue-fraction threshold. Training aborted.")
        raise ExtractionError("No tissue patches passed the tissue-fraction threshold.")

    print_info(f"Collected {len(picked)} tissue patches from {len(files)} files.")

    # ── Phase 2: fit ────────────────────────────────────────────────────────
    print_step("FIT", f"Fitting {cfg.n_type.upper()} normaliser …")

    if is_reinhard:
        normalizer.fit_from_patches(picked)
    else:
        cap = cfg.max_train_patches
        if len(picked) > cap:
            rng = np.random.default_rng(seed=42)
            picked = [picked[i] for i in rng.choice(len(picked), cap, replace=False)]
            print_info(f"Subsampled to {cap} patches for mosaic construction.")

        side = int(np.ceil(np.sqrt(len(picked))))
        canvas = np.zeros((side * 256, side * 256, 3), dtype=np.uint8)
        for idx, patch in enumerate(picked):
            r, c = divmod(idx, side)
            canvas[r * 256 : (r + 1) * 256, c * 256 : (c + 1) * 256] = patch
        print_info(f"Mosaic built: {canvas.shape[1]}×{canvas.shape[0]} px.")

        normalizer.fit(canvas)
        del canvas

    # ── Phase 3: save ─────────────────────────────────────────────────────
    print_step("SAVE", f"Writing weights → {weights}")
    normalizer.save_weights(weights)
    print_done(f"Weights saved → {weights}")
    return weights


def run_stain_normalization_apply(
    input_dir: str,
    output_dir: str,
    cfg: Optional[StainNormalizationConfig] = None,
) -> Dict[str, int]:
    """Apply pre-fitted normaliser weights to a folder of patches.

    Parameters
    ----------
    input_dir : str
    output_dir : str
        Normalised images are written under ``<output_dir>/normalized_images``,
        mirroring the relative path of each input file.
    cfg : StainNormalizationConfig or None

    Returns
    -------
    dict
        ``{"processed": int, "skipped": int, "failed": int, "total": int}``
    """
    if cfg is None:
        cfg = StainNormalizationConfig()

    files = discover_files(input_dir, cfg.stains)
    normalizer = get_normalizer(cfg.n_type)
    layout = OutputLayout(output_dir)
    out_root = layout.module_dir("stain_normalization")
    weights = Path(cfg.weights_path) if cfg.weights_path else out_root / f"{cfg.n_type}_weights.npz"

    print_banner()

    if not files:
        print_error(f"No patches found in '{input_dir}' for stains {cfg.stains}. Aborting.")
        raise ExtractionError(f"No patches found in '{input_dir}' for stains {cfg.stains}")

    if not weights.is_file():
        print_error(f"Weights file not found: {weights}. Run train mode first.")
        raise ExtractionError(f"Weights file not found: {weights}")

    print_section("Applying Normalisation")
    print_summary_table(
        [
            ("Algorithm", cfg.n_type.upper()),
            ("Input dir", input_dir),
            ("Weights", str(weights)),
            ("Output dir", str(out_root)),
            ("Patches", len(files)),
            ("Resume", "yes" if cfg.resume else "no"),
        ],
        title="Apply Config",
    )

    print_step("LOAD", f"Loading weights ← {weights}")
    normalizer.load_weights(weights)

    processed = skipped = failed = 0

    print_step("NORM", "Normalising patches …")
    for fp in track(files, "Normalising"):
        relative = fp.relative_to(input_dir)
        item_name = "__".join(relative.with_suffix("").parts)
        out_path = layout.item_dir("stain_normalization", item_name) / fp.name

        if cfg.resume and out_path.exists():
            skipped += 1
            continue

        try:
            img = imread_rgb(fp)
            if img is None:
                raise ValueError("imread returned None")
            imwrite_rgb(out_path, normalizer.transform(img))
            processed += 1
        except Exception as exc:
            failed += 1
            print_warn(f"Failed [{fp.name}]: {exc}")

    print_counts(ok=processed, fail=failed, label="Normalisation")
    print_summary_table(
        [
            ("Total", len(files)),
            ("Processed", processed),
            ("Skipped", skipped),
            ("Failed", failed),
            ("Output", str(out_root)),
        ],
        title="Apply Results",
    )
    print_done("Normalisation complete.")

    return {"processed": processed, "skipped": skipped, "failed": failed, "total": len(files)}
