#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rocqipath  —  Interactive CLI
====================================
Entry point for the rocqipath whole-slide image (WSI) processing pipeline.

Menu
────
    1. Alignment Pipeline      — register all H&E / IHC pairs under a
                                  directory tree (drives rocqipath.registration).
    2. Core Extraction         — detect and extract tissue cores from paired
                                  multi-region slides (drives rocqipath.extraction).
    3. Stain Normalization     — train or apply Reinhard/Macenko/Vahadane
                                  normalisers (drives rocqipath.stain).
    4. Exit

Everything else — single-slide patch extraction, WSI thumbnail export,
grid-map figures, and patch-pair visualisation — is available as a clean
importable API via ``rocqipath.api``.  See the README for examples.
"""

import os
from typing import List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# Logging
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# Guarded imports
# ══════════════════════════════════════════════════════════════════════════════

from rocqipath.logger import logger

try:
    from .registration import AlignmentConfig, run_alignment

    HAS_ALIGNMENT = True
except (ImportError, OSError) as _e:
    HAS_ALIGNMENT = False
    logger.debug("Alignment module unavailable: {}", _e)

try:
    from .extraction import (
        CoreExtractionConfig,
        TissueExtractionConfig,
        run_core_extraction_pipeline as _run_extraction,
        run_tissue_pipeline as _run_tissue_extraction,
    )

    HAS_EXTRACTION = True
except (ImportError, OSError) as _e:
    HAS_EXTRACTION = False
    logger.debug("Extraction module unavailable: {}", _e)

try:
    from .stain import (
        StainNormalizationConfig,
        run_stain_normalization_train as _run_stain_train,
        run_stain_normalization_apply as _run_stain_apply,
    )

    HAS_STAIN_NORM = True
except (ImportError, OSError) as _e:
    HAS_STAIN_NORM = False
    logger.debug("Stain normalization module unavailable: {}", _e)


# ══════════════════════════════════════════════════════════════════════════════
# Input helpers
# ══════════════════════════════════════════════════════════════════════════════


def _get_existing_dir(prompt: str) -> str:
    """Prompt for a directory path that must already exist.

    Blocks in a loop until a non-empty path is entered that resolves
    (after quote-stripping, ``~`` expansion, and absolute-path
    resolution) to an existing directory, or the user declines to retry.

    Parameters
    ----------
    prompt : str
        The prompt text shown to the user (including any trailing
        ``": "`` — not added automatically by this function).

    Returns
    -------
    str
        The resolved absolute path of the validated, existing directory.

    Raises
    ------
    SystemExit
        If the entered path doesn't exist and the user answers anything
        other than ``"y"`` when asked whether to retry.
    """
    while True:
        raw = input(prompt).strip().replace('"', "").replace("'", "")
        if not raw:
            print("  Path cannot be empty.")
            continue
        p = os.path.abspath(os.path.expanduser(raw))
        if os.path.isdir(p):
            return p
        print(f"  Directory not found: {p}")
        if input("  Retry? (y/n): ").strip().lower() != "y":
            raise SystemExit("Cancelled.")


def _get_dir(prompt: str) -> str:
    """Prompt for a directory path, creating it if it doesn't already exist.

    Unlike :func:`_get_existing_dir`, this is for *output* directories —
    a missing path is not an error, it's simply created.

    Parameters
    ----------
    prompt : str
        The prompt text shown to the user.

    Returns
    -------
    str
        The resolved absolute path of the (now-existing) directory.
    """
    while True:
        raw = input(prompt).strip().replace('"', "").replace("'", "")
        if not raw:
            print("  Path cannot be empty.")
            continue
        p = os.path.abspath(os.path.expanduser(raw))
        os.makedirs(p, exist_ok=True)
        return p


def _get_int(prompt: str, default: int, min_val: int = 0) -> int:
    """Prompt for an integer, showing and accepting a default on empty input.

    Parameters
    ----------
    prompt : str
        The prompt text; the default value is appended automatically in
        ``[brackets]``.
    default : int
        Value returned if the user presses Enter without typing
        anything.
    min_val : int, optional
        Minimum acceptable value (inclusive). Defaults to ``0``. Input
        below this re-prompts rather than raising.

    Returns
    -------
    int
        The validated integer — either ``default`` (on empty input) or
        the user's entered value, guaranteed ``>= min_val``.

    Notes
    -----
    Non-numeric input and values below ``min_val`` both re-prompt with
    an explanatory message rather than raising, so a typo never crashes
    the interactive session.
    """
    while True:
        raw = input(f"  {prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if val < min_val:
                print(f"  Value must be >= {min_val}.")
                continue
            return val
        except ValueError:
            print("  Please enter a valid integer.")


def _get_float(prompt: str, default: float) -> float:
    """Prompt for a float, showing and accepting a default on empty input.

    Parameters
    ----------
    prompt : str
        The prompt text; the default value is appended automatically in
        ``[brackets]``.
    default : float
        Value returned if the user presses Enter without typing
        anything.

    Returns
    -------
    float
        The validated float — either ``default`` (on empty input) or the
        user's entered value.

    Notes
    -----
    Non-numeric input re-prompts with an explanatory message rather than
    raising. Unlike :func:`_get_int`, there is no minimum-value check
    here — any parseable float is accepted.
    """
    while True:
        raw = input(f"  {prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a valid number.")


def _get_bool(prompt: str, default: bool) -> bool:
    """Prompt for a yes/no answer, showing and accepting a default on empty input.

    Parameters
    ----------
    prompt : str
        The prompt text; a ``[y]`` or ``[n]`` hint (matching ``default``)
        is appended automatically.
    default : bool
        Value returned if the user presses Enter without typing
        anything.

    Returns
    -------
    bool
        ``default`` on empty input; otherwise ``True`` if the
        (lowercased) response is one of ``"y"``, ``"yes"``, ``"1"``, or
        ``"true"``, and ``False`` for any other non-empty input
        (including typos — there is no re-prompt loop here, unlike the
        other ``_get_*`` helpers, so an unrecognised response is
        silently treated as "no").
    """
    d_str = "y" if default else "n"
    raw = input(f"  {prompt} [{d_str}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def _get_optional_float(prompt: str) -> Optional[float]:
    """Prompt for an optional float, where empty or "none" both mean "unset".

    Parameters
    ----------
    prompt : str
        The prompt text; a ``[none]`` hint is appended automatically.

    Returns
    -------
    float or None
        ``None`` if the input is empty or (case-insensitively) the
        literal word ``"none"``, or if the input cannot be parsed as a
        float (invalid input is treated as "unset" rather than
        re-prompting, unlike most of the other ``_get_*`` helpers).
        Otherwise, the parsed float value.
    """
    raw = input(f"  {prompt} [none]: ").strip()
    if not raw or raw.lower() == "none":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _get_stain_list(prompt: str) -> List[str]:
    """Prompt for a comma-separated list of stain/biomarker labels.

    Parameters
    ----------
    prompt : str
        The prompt text; an ``[all]`` hint is appended automatically.

    Returns
    -------
    list of str
        ``["all"]`` if the input is empty or (case-insensitively) the
        literal word ``"all"`` — the convention used throughout this
        package's pipelines to mean "don't filter by stain, process
        everything". Otherwise, the comma-separated input split into
        individual labels, each stripped of surrounding whitespace, with
        empty entries (e.g. from trailing commas) dropped.
    """
    raw = input(f"  {prompt} [all]: ").strip()
    if not raw or raw.lower() == "all":
        return ["all"]
    return [s.strip() for s in raw.split(",") if s.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# Menu command 1 — Alignment Pipeline
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_alignment() -> None:
    """
    Interactive setup for the WSI alignment pipeline.

    Collects the minimum required paths and lets the user accept sensible
    defaults for every other parameter.  Drives
    :func:`rocqipath.registration.run_alignment`.

    Expected input structure::

        <input_dir>/
            <biomarker>/
                he/   <- H&E WSI files
                ihc/  <- IHC WSI files

    Biomarker subfolders are auto-discovered when left blank.
    """
    if not HAS_ALIGNMENT:
        logger.error(
            "rocqipath.registration is not available. "
            "Ensure rocqipath.registration.core is installed."
        )
        return

    print("\n" + "─" * 72)
    print("  Alignment Pipeline")
    print("─" * 72)
    print("  Register H&E / IHC slide pairs and save aligned OME-TIFFs.")
    print("  Press Enter to accept defaults shown in [brackets].\n")

    input_dir = _get_existing_dir("  Input directory (contains biomarker subfolders): ")
    output_dir = _get_dir("  Output directory: ")

    raw_bio = input("  Biomarker folders to process (comma-separated, or Enter for all): ").strip()
    biomarker_folders = [b.strip() for b in raw_bio.split(",") if b.strip()] if raw_bio else []

    print("\n  Registration settings:")
    method = input("  Method — valis / orb [valis]: ").strip().lower() or "valis"
    if method not in ("valis", "orb"):
        print("  Unknown method — defaulting to valis.")
        method = "valis"

    aligned_wsi_level = _get_int("Aligned WSI pyramid level (0 = full res)", 0, 0)
    valis_max_err = _get_optional_float("Max acceptable VALIS error in um (Enter = no limit)")
    qc_enabled = _get_bool("Save centre-patch QC PNG per case?", False)

    print("\n  Patch / grid settings (forwarded to WSIRegistrar):")
    patch_size = _get_int("Patch size px", 512, 1)
    grid_density = _get_int("Grid density rows", 10, 1)

    cfg = AlignmentConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        biomarker_folders=biomarker_folders,
        alignment_method=method,
        aligned_wsi_level=aligned_wsi_level,
        valis_max_error_um=valis_max_err,
        qc_enabled=qc_enabled,
        patch_size=patch_size,
        grid_density=grid_density,
        target_magnification=_get_float("Target magnification (physical x)", 20.0),
    )

    print(f"\n  Starting alignment -> {output_dir}\n")
    try:
        results = run_alignment(cfg)
        print(f"\n  Done - {len(results)} case(s) processed.")
    except Exception as e:
        logger.exception(f"Alignment pipeline failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Menu command 2 — WSI tissue extraction
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_tissue_extraction() -> None:
    """Configure tissue extraction for ordinary whole-slide sections."""
    if not HAS_EXTRACTION:
        logger.error("Tissue extraction is unavailable; install the extraction extra.")
        return
    print("\n" + "─" * 72)
    print("  Tissue Extraction — WSI mode")
    print("─" * 72)
    input_dir = _get_existing_dir("  Input directory: ")
    output_dir = _get_dir("  General output root: ")
    target_mag = _get_float("Output magnification (physical x)", 20.0)
    detection_mag = _get_float("Detection magnification (physical x)", 1.25)
    source_mag = _get_optional_float(
        "Source objective x if slide metadata is missing (Enter = metadata)"
    )
    cfg = TissueExtractionConfig(
        target_magnification=target_mag,
        detection_magnification=detection_mag,
        source_magnification=source_mag,
        min_area_fraction=_get_float("Min area fraction", 0.005),
        skip_existing=_get_bool("Skip complete existing regions?", True),
    )
    _run_tissue_extraction(input_dir, output_dir, cfg)


# ══════════════════════════════════════════════════════════════════════════════
# Menu command 3 — TMA/core extraction
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_extraction() -> None:
    """
    Interactive setup for the multi-region (core) extraction pipeline.

    Collects paths and stain targets, then lets the user tune all
    CoreExtractionConfig parameters with press-Enter defaults.  Drives
    :func:`rocqipath.extraction.run_core_extraction_pipeline`.
    """
    if not HAS_EXTRACTION:
        logger.error(
            "rocqipath.extraction is not available. Ensure pyvips and opencv-python are installed."
        )
        return

    print("\n" + "─" * 72)
    print("  Tissue Extraction — TMA/core mode")
    print("─" * 72)
    print("  Detect and extract tissue cores from paired H&E + IHC slides")
    print("  containing multiple discrete tissue regions.")
    print("  Press Enter to accept defaults shown in [brackets].\n")

    input_dir = _get_existing_dir("  Input directory: ")
    output_dir = _get_dir("  Output directory: ")
    target_stains = _get_stain_list("Target stains/biomarkers, e.g. H&E,marker_A")

    print("\n  Extraction parameters:")
    target_mag = _get_float("Output magnification (physical x)", 20.0)
    detection_mag = _get_float("Detection magnification (physical x)", 1.25)
    source_mag = _get_optional_float(
        "Source objective x if metadata is missing (e.g. 80; Enter = metadata)"
    )
    min_area_fraction = _get_float("Min area fraction (e.g. 0.0005)", 0.0005)
    min_circularity = _get_float("Min circularity [0-1]", 0.70)
    only_circles = _get_bool("Circles only?", True)
    box_scale = _get_float("Box scale (1.0 = exact fit)", 1.0)
    per_stain = _get_bool("Per-stain Otsu detection?", True)
    fallback_to_he = _get_bool("Fallback to H&E on count mismatch?", True)
    ihc_enhance = _get_bool("Apply IHC CLAHE enhancement?", True)
    skip_existing = _get_bool("Skip already-processed cores?", True)

    cfg = CoreExtractionConfig(
        target_magnification=target_mag,
        detection_magnification=detection_mag,
        source_magnification=source_mag,
        min_area_fraction=min_area_fraction,
        min_circularity=min_circularity,
        only_circles=only_circles,
        box_scale=box_scale,
        per_stain_detection=per_stain,
        fallback_to_he=fallback_to_he,
        ihc_enhance=ihc_enhance,
        skip_existing=skip_existing,
    )

    print(f"\n  Starting extraction -> {output_dir}\n")
    try:
        _run_extraction(
            input_dir=input_dir,
            output_root=output_dir,
            cfg=cfg,
            target_stains=target_stains,
        )
    except Exception as e:
        logger.exception(f"Extraction pipeline failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Menu command 3 — Stain Normalization
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_stain_normalization() -> None:
    """
    Interactive setup for the stain normalisation train / apply workflow.

    Drives :func:`rocqipath.stain.run_stain_normalization_train`
    and :func:`rocqipath.stain.run_stain_normalization_apply`.
    """
    if not HAS_STAIN_NORM:
        logger.error("rocqipath.stain is not available. Ensure tiatoolbox is installed.")
        return

    print("\n" + "─" * 72)
    print("  Stain Normalization")
    print("─" * 72)
    print("  Train a Reinhard / Macenko / Vahadane normaliser, or apply")
    print("  previously saved weights to a folder of patches.")
    print("  Press Enter to accept defaults shown in [brackets].\n")

    mode = input("  Mode — train / apply [train]: ").strip().lower() or "train"
    if mode not in ("train", "apply"):
        print("  Unknown mode — defaulting to train.")
        mode = "train"

    input_dir = _get_existing_dir("  Input directory: ")
    output_dir = _get_dir("  Output directory: ")
    n_type = (
        input("  Algorithm — reinhard / macenko / vahadane [macenko]: ").strip().lower()
        or "macenko"
    )
    stains = _get_stain_list("Stain folder tokens, e.g. he")

    if mode == "train":
        fit_min_tissue = _get_float("Min tissue fraction to use a patch [0-1]", 0.1)
        max_train_patches = _get_int("Max patches for mosaic (Macenko/Vahadane)", 1000, 1)
        cfg = StainNormalizationConfig(
            n_type=n_type,
            stains=stains,
            fit_min_tissue=fit_min_tissue,
            max_train_patches=max_train_patches,
        )
        print(f"\n  Starting training -> {output_dir}\n")
        try:
            _run_stain_train(input_dir, output_dir, cfg)
        except Exception as e:
            logger.exception(f"Stain normalization training failed: {e}")
    else:
        resume = _get_bool("Skip patches already normalised (resume)?", False)
        cfg = StainNormalizationConfig(n_type=n_type, stains=stains, resume=resume)
        print(f"\n  Starting normalisation -> {output_dir}\n")
        try:
            _run_stain_apply(input_dir, output_dir, cfg)
        except Exception as e:
            logger.exception(f"Stain normalization apply failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Main menu
# ══════════════════════════════════════════════════════════════════════════════

_SEP = "=" * 72

_DISPATCH = {
    "1": _cmd_alignment,
    "2": _cmd_tissue_extraction,
    "3": _cmd_extraction,
    "4": _cmd_stain_normalization,
}


def _print_header() -> None:
    """Print the interactive CLI's main menu header and options.

    Displayed once per iteration of :func:`main_menu`'s loop, before
    prompting for a choice. Pulls the current package version
    dynamically from ``rocqipath.__version__`` (rather than a hardcoded
    string) so the displayed version never drifts out of sync with the
    installed package.
    """
    import rocqipath

    print("\n" + _SEP)
    print(f"  rocqipath  |  Author: Darshil Gajjar  |  Version: v{rocqipath.__version__}")
    print(_SEP)
    print("  Main Menu:")
    print("    1.  Alignment Pipeline")
    print("    2.  Tissue Extraction — WSI")
    print("    3.  Tissue Extraction — TMA/core")
    print("    4.  Stain Normalization")
    print("    5.  Exit")
    print()
    print("  Tip: single-slide patch extraction, WSI thumbnail export,")
    print("  grid maps, and visualisation are importable from rocqipath.api")
    print()


def main_menu() -> None:
    """Run the interactive menu loop until the user selects Exit."""
    while True:
        _print_header()
        choice = input("  Enter choice (1-5): ").strip()

        if choice == "5":
            print("\n  Exiting RocqiPath. Goodbye.\n")
            break
        elif choice in _DISPATCH:
            try:
                _DISPATCH[choice]()
            except SystemExit:
                pass
            except KeyboardInterrupt:
                print("\n  (Interrupted - returning to menu)")
        else:
            print(f"  Invalid choice '{choice}'. Please enter 1, 2, 3, 4, or 5.")


def main() -> int:
    """
    Entry point for the ``rocqipath`` console script.

    Returns 0 on clean exit, 130 on KeyboardInterrupt.
    """
    try:
        main_menu()
        return 0
    except KeyboardInterrupt:
        print("\n  Interrupted by user.\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
