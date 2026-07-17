# -*- coding: utf-8 -*-
"""
roqcipath.api
==================
Importable utility functions for common WSI processing tasks.

These were previously embedded in the interactive CLI menu.  They are now
available as a clean programmatic API so you can call them from notebooks,
scripts, or downstream pipelines without launching the interactive CLI.

────────────────────────────────────────────────────────────────────────────
Quick reference
────────────────────────────────────────────────────────────────────────────

Patch extraction (single slide, no registration)::

    from roqcipath.api import extract_patches_single

    extract_patches_single(
        input_dir  = "./data/wsi",
        output_dir = "./out",
        wsi_files  = ["slide_01.svs"],   # or None / [] for all slides
        patch_size = 512,
        grid_density = 20,
        grid_ids   = [5, 12, 17],        # or None for all tissue grids
    )

Grid-map export::

    from roqcipath.api import export_grid_map, export_paired_grid_maps

    export_grid_map("slide_01.svs", "./maps", grid_density=20)

    export_paired_grid_maps(
        input_dir    = "./data/wsi",
        output_dir   = "./maps",
        biomarker    = "Meca79",
        grid_density = 20,
    )

WSI thumbnail export::

    from roqcipath.api import export_wsi_thumbnails

    export_wsi_thumbnails(
        input_dir   = "./data/wsi",
        output_dir  = "./thumbs",
        wsi_files   = None,    # None = all slides
        max_dim     = 5000,
        fmt         = "png",
    )

Patch-pair visualisation::

    from roqcipath.api import visualize_patch_pairs

    visualize_patch_pairs(
        grid_folder = "./out/patch_extraction/slide_01",
        num_to_show = 10,
    )
"""

from __future__ import annotations

__all__ = [
    # Patch extraction
    "extract_patches_single",
    # Grid maps
    "export_grid_map",
    "export_paired_grid_maps",
    # WSI thumbnails
    "export_wsi_thumbnails",
    # Visualisation
    "visualize_patch_pairs",
    # Low-level helpers re-exported for convenience
    "generate_single_grid_map_for_slide",
    "save_paired_grid_map_figure",
]

import os
import shutil
import tempfile
from roqcipath.logger import logger  # noqa: E402
from roqcipath.output import OutputLayout
from pathlib import Path
from typing import List, Optional, Union


# ── Internal imports (guarded so this module can be imported in dry-run envs) ─
try:
    from roqcipath.config import DEFAULT_CONFIG
    from roqcipath.registration.core import WSIRegistrar
    from roqcipath.visualization import plot_selector_map, view_pairs
    from roqcipath.utils import (
        list_wsi_files,
        detect_wsi_format,
        find_hne_ihc_pairs_by_suffix,
    )
    _HAS_CORE = True
except ImportError as _e:
    _HAS_CORE = False
    logger.warning(f"roqcipath.registration.core not fully available: {_e}")


# ══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _require_core() -> None:
    """Raise if roqcipath.registration.core (and its dependencies) isn't available.

    Called at the top of every :mod:`roqcipath.api` function that needs
    :class:`~roqcipath.registration.core.WSIRegistrar` — a guard clause
    that turns a potential ``NameError``/``AttributeError`` deep inside a
    function body into a clear, actionable error raised immediately at
    the call site.

    Raises
    ------
    RuntimeError
        If the module-level import of ``roqcipath.registration.core``
        (and its transitive dependencies — OpenSlide, VALIS, OpenCV)
        failed when this module was first imported, as recorded in the
        module-level ``_HAS_CORE`` flag.
    """
    if not _HAS_CORE:
        raise RuntimeError(
            "roqcipath.registration.core is not available. "
            "Install openslide-python, valis-wsi, and opencv-python."
        )


def _build_cfg(
    *,
    input_dir:    str,
    output_dir:   str,
    patch_size:   int = 512,
    grid_density: int = 20,
) -> dict:
    """Construct a minimal WSIRegistrar config dict."""
    cfg = DEFAULT_CONFIG.copy()
    cfg.update({
        "base_input_dir":  input_dir,
        "base_output_dir": output_dir,
        "patch_size":      patch_size,
        "grid_density":    grid_density,
    })
    return cfg


# ══════════════════════════════════════════════════════════════════════════════
# Grid map helpers
# ══════════════════════════════════════════════════════════════════════════════

def generate_single_grid_map_for_slide(
    wsi_path:     str,
    output_dir:   str,
    cfg:          dict,
) -> tuple:
    """
    Generate and save a tissue grid-map PNG for a single slide.

    Performs lightweight pre-flight checks (OpenSlide compatibility, pyramidal
    structure) before running ``WSIRegistrar.generate_grid_map()`` and
    ``plot_selector_map()``.

    Parameters
    ----------
    wsi_path   : str     Absolute path to the WSI file.
    output_dir : str     Directory where the grid-map PNG is saved.
    cfg        : dict    Config dict (must contain ``"grid_density"``).

    Returns
    -------
    (success, map_path, reason) : (bool, str | None, str | None)
        ``success``  — ``True`` if the grid map was saved successfully.
        ``map_path`` — absolute path to the PNG, or ``None`` on failure.
        ``reason``   — human-readable failure reason, or ``None`` on success.
    """
    _require_core()
    info = detect_wsi_format(wsi_path)

    if not info["openslide_compatible"]:
        return False, None, "OpenSlide incompatible"
    if info["is_pyramidal"] is False:
        return False, None, "Not pyramidal / not WSI-like"

    registrar = WSIRegistrar(wsi_path, None, cfg)
    try:
        thumb, valid_grids = registrar.generate_grid_map()
        if thumb is None:
            return False, None, "Thumbnail generation failed"
        if not valid_grids:
            return False, None, "No valid tissue grids found"

        base_name = os.path.splitext(os.path.basename(wsi_path))[0]
        map_path  = os.path.join(output_dir, f"{base_name}_grid_map.png")
        plot_selector_map(
            thumb, valid_grids,
            cfg["grid_density"], cfg["grid_density"],
            map_path,
        )
        return True, map_path, None
    except Exception as e:
        return False, None, str(e)
    finally:
        try:
            registrar.close()
        except Exception:
            pass


def save_paired_grid_map_figure(
    hne_map_path: str,
    ihc_map_path: str,
    save_path:    str,
    hne_title:    str,
    ihc_title:    str,
) -> None:
    """
    Render and save a side-by-side H&E / IHC grid-map figure at 300 DPI.

    Parameters
    ----------
    hne_map_path : str     Path to the H&E grid-map PNG.
    ihc_map_path : str     Path to the IHC grid-map PNG.
    save_path    : str     Destination path for the combined figure (PNG).
    hne_title    : str     Subplot title for the H&E panel.
    ihc_title    : str     Subplot title for the IHC panel.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    hne_img = Image.open(hne_map_path).convert("RGB")
    ihc_img = Image.open(ihc_map_path).convert("RGB")

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    axes[0].imshow(hne_img);  axes[0].set_title(hne_title, fontsize=12);  axes[0].axis("off")
    axes[1].imshow(ihc_img);  axes[1].set_title(ihc_title, fontsize=12);  axes[1].axis("off")
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def extract_patches_single(
    input_dir:    str,
    output_dir:   str,
    *,
    wsi_files:    Optional[List[str]] = None,
    patch_size:   int                 = 512,
    grid_density: int                 = 20,
    grid_ids:     Optional[List[int]] = None,
) -> None:
    """
    Extract patches from one or more slides without IHC pairing or
    registration.

    Useful for reference-only patch mining (H&E only, or any single stain).
    Patches are saved under ``<output_dir>/alignment/<slide_name>/`` with grid
    identifiers encoded in filenames.

    Parameters
    ----------
    input_dir    : str            Directory containing WSI files.
    output_dir   : str            Root output directory.
    wsi_files    : list[str] or None
        Specific filenames to process.  ``None`` or ``[]`` → all WSI files
        found in *input_dir*.
    patch_size   : int            Patch edge length in pixels (default 512).
    grid_density : int            Grid rows/columns (default 20).
    grid_ids     : list[int] or None
        Specific grid IDs to extract.  ``None`` → all tissue grids.

    Example
    -------
    ::

        from roqcipath.api import extract_patches_single

        extract_patches_single(
            input_dir    = "./data/wsi",
            output_dir   = "./patches",
            patch_size   = 256,
            grid_density = 10,
            grid_ids     = [0, 1, 5],
        )
    """
    _require_core()
    os.makedirs(output_dir, exist_ok=True)
    cfg = _build_cfg(
        input_dir    = input_dir,
        output_dir   = output_dir,
        patch_size   = patch_size,
        grid_density = grid_density,
    )

    all_files = list_wsi_files(input_dir)
    files_to_process = wsi_files if wsi_files else all_files
    if not files_to_process:
        logger.warning(f"No WSI files found in {input_dir}")
        return

    for wsi_file in files_to_process:
        wsi_path  = os.path.join(input_dir, wsi_file)
        registrar = WSIRegistrar(wsi_path, None, cfg)
        try:
            thumb, valid_grids = registrar.generate_grid_map()
            target_grids = grid_ids if grid_ids is not None else valid_grids

            map_path = os.path.join(registrar.output_dir, "grid_map.png")
            plot_selector_map(
                thumb, valid_grids,
                grid_density, grid_density,
                map_path,
            )

            for gid in target_grids:
                if gid not in valid_grids:
                    logger.warning(f"{wsi_file}: grid {gid} is not tissue — skipping")
                    continue
                count = registrar.extract_single_patch(gid)
                logger.info(f"{wsi_file}: grid {gid} → {count} patches")

        except Exception as e:
            logger.error(f"Failed for {wsi_path}: {e}")
        finally:
            try:
                registrar.close()
            except Exception:
                pass


def export_grid_map(
    wsi_path:     str,
    output_dir:   str,
    *,
    grid_density: int = 20,
) -> Optional[str]:
    """
    Generate and save a tissue grid-map PNG for a single WSI.

    Parameters
    ----------
    wsi_path     : str   Absolute path to the WSI file.
    output_dir   : str   Directory where the PNG is saved.
    grid_density : int   Grid rows/columns (default 20).

    Returns
    -------
    str or None
        Path to the saved grid-map PNG, or ``None`` on failure.

    Example
    -------
    ::

        from roqcipath.api import export_grid_map

        path = export_grid_map("./data/slide_01.svs", "./maps", grid_density=20)
        print("Saved to:", path)
    """
    _require_core()
    os.makedirs(output_dir, exist_ok=True)
    cfg = _build_cfg(
        input_dir    = os.path.dirname(wsi_path),
        output_dir   = output_dir,
        grid_density = grid_density,
    )
    success, map_path, reason = generate_single_grid_map_for_slide(
        wsi_path, output_dir, cfg
    )
    if not success:
        logger.warning(f"Grid map failed for {wsi_path}: {reason}")
        return None
    return map_path


def export_paired_grid_maps(
    input_dir:    str,
    output_dir:   str,
    biomarker:    str,
    *,
    grid_density: int = 20,
) -> dict:
    """
    Generate and save side-by-side H&E + IHC grid-map figures for all suffix-
    paired slides in *input_dir*.

    Pairing uses :func:`~roqcipath.utils.find_hne_ihc_pairs_by_suffix`
    (the ``mF1 / mE5`` naming convention).

    Parameters
    ----------
    input_dir    : str   Directory containing WSI files.
    output_dir   : str   Root output directory.
    biomarker    : str   IHC biomarker name (e.g. ``"Meca79"``).
    grid_density : int   Grid rows/columns (default 20).

    Returns
    -------
    dict
        ``{"saved": int, "skipped": int}`` summary counts.

    Example
    -------
    ::

        from roqcipath.api import export_paired_grid_maps

        summary = export_paired_grid_maps(
            input_dir    = "./data/wsi",
            output_dir   = "./maps",
            biomarker    = "Meca79",
            grid_density = 20,
        )
        print(summary)
    """
    _require_core()
    layout = OutputLayout(output_dir)
    single_dir = tempfile.mkdtemp(prefix="roqcipath_grid_maps_")

    cfg = _build_cfg(
        input_dir    = input_dir,
        output_dir   = output_dir,
        grid_density = grid_density,
    )

    files = list_wsi_files(input_dir)
    pairs = find_hne_ihc_pairs_by_suffix(files, biomarker)
    if not pairs:
        logger.warning(
            f"No H&E / {biomarker} suffix-pairs found in {input_dir}"
        )
        shutil.rmtree(single_dir, ignore_errors=True)
        return {"saved": 0, "skipped": 0}

    saved = skipped = 0

    for pair in pairs:
        suffix   = pair["suffix"]
        hne_path = os.path.join(input_dir, pair["hne"])
        ihc_path = os.path.join(input_dir, pair["ihc"])

        hne_ok, hne_map, hne_reason = generate_single_grid_map_for_slide(
            hne_path, single_dir, cfg
        )
        if not hne_ok:
            logger.warning(f"SKIP {suffix}: H&E grid map failed — {hne_reason}")
            skipped += 1
            continue

        ihc_ok, ihc_map, ihc_reason = generate_single_grid_map_for_slide(
            ihc_path, single_dir, cfg
        )
        if not ihc_ok:
            logger.warning(f"SKIP {suffix}: IHC grid map failed — {ihc_reason}")
            skipped += 1
            continue

        pair_dir = layout.item_dir("visualization", f"{suffix}_{biomarker}")
        save_path = str(pair_dir / f"{suffix}_{biomarker}_paired_grid_map.png")
        try:
            save_paired_grid_map_figure(
                hne_map_path = hne_map,
                ihc_map_path = ihc_map,
                save_path    = save_path,
                hne_title    = f"H&E ({suffix})",
                ihc_title    = f"{biomarker} ({suffix})",
            )
            logger.info(f"SAVED: {save_path}")
            saved += 1
        except Exception as e:
            logger.warning(f"SKIP {suffix}: figure save failed — {e}")
            skipped += 1

    shutil.rmtree(single_dir, ignore_errors=True)
    logger.info(f"export_paired_grid_maps: saved={saved}  skipped={skipped}")
    return {"saved": saved, "skipped": skipped}


def export_wsi_thumbnails(
    input_dir:   str,
    output_dir:  str,
    *,
    wsi_files:   Optional[List[str]] = None,
    max_dim:     int                 = 5000,
    fmt:         str                 = "png",
    jpeg_quality: int                = 95,
    overwrite:   bool                = False,
) -> List[str]:
    """
    Export WSI thumbnails at a configurable resolution and format.

    All exports are saved under ``<output_dir>/WSI_Exports/``.

    Parameters
    ----------
    input_dir    : str            Directory containing WSI files.
    output_dir   : str            Root output directory.
    wsi_files    : list[str] or None
        Specific filenames to export.  ``None`` or ``[]`` → all WSI files
        found in *input_dir*.
    max_dim      : int            Maximum edge size in pixels (default 5000).
    fmt          : str            Format: ``"png"`` | ``"jpeg"`` | ``"tiff"``.
    jpeg_quality : int            JPEG quality 1–100 (ignored for png/tiff).
    overwrite    : bool           Overwrite existing files (default False).

    Returns
    -------
    List[str]
        Absolute paths of all successfully exported thumbnail files.

    Example
    -------
    ::

        from roqcipath.api import export_wsi_thumbnails

        paths = export_wsi_thumbnails(
            input_dir = "./data/wsi",
            output_dir = "./thumbs",
            max_dim    = 3000,
            fmt        = "jpeg",
        )
    """
    _require_core()
    try:
        import openslide
    except ImportError:
        raise RuntimeError(
            "openslide-python is required for WSI thumbnail export."
        )

    layout = OutputLayout(output_dir)

    fmt = fmt.lower()
    ext = "jpg" if fmt in ("jpeg", "jpg") else ("tif" if fmt in ("tiff", "tif") else "png")

    all_files = list_wsi_files(input_dir)
    files_to_export = wsi_files if wsi_files else all_files
    if not files_to_export:
        logger.warning(f"No WSI files found in {input_dir}")
        return []

    exported: List[str] = []

    for wsi_file in files_to_export:
        wsi_path = os.path.join(input_dir, wsi_file)
        base     = os.path.splitext(os.path.basename(wsi_path))[0]
        out_path = str(layout.item_dir("visualization", base) / f"{base}_export.{ext}")

        if os.path.exists(out_path) and not overwrite:
            logger.info(f"Exists (skip): {out_path}")
            exported.append(out_path)
            continue

        try:
            slide = openslide.OpenSlide(wsi_path)
            w, h  = slide.dimensions
            if w >= h:
                tw, th = max_dim, int(max_dim * h / w)
            else:
                tw, th = int(max_dim * w / h), max_dim

            thumb = slide.get_thumbnail((tw, th)).convert("RGB")
            if ext == "jpg":
                thumb.save(out_path, quality=jpeg_quality)
            else:
                thumb.save(out_path)
            slide.close()

            logger.info(f"Exported: {out_path}")
            exported.append(out_path)

        except Exception as e:
            logger.error(f"Export failed for {wsi_path}: {e}")

    return exported


def visualize_patch_pairs(
    grid_folder:  str,
    num_to_show:  Union[int, str] = "all",
) -> None:
    """
    Visualise extracted H&E / IHC patch pairs side-by-side.

    Wraps :func:`roqcipath.visualization.view_pairs`.

    Parameters
    ----------
    grid_folder  : str           Path to a flat patch-extraction case folder.
    num_to_show  : int or "all"  Number of pairs to display.  ``"all"``
                                 shows every available pair.

    Example
    -------
    ::

        from roqcipath.api import visualize_patch_pairs

        visualize_patch_pairs(
            "./out/patch_extraction/slide_01",
            num_to_show=10,
        )
    """
    _require_core()
    view_pairs(grid_folder, num_to_show=num_to_show)
