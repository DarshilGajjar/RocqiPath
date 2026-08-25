"""Generate single-slide and paired WSI grid-map figures."""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Optional, Tuple

import matplotlib.patches as patches
import matplotlib.pyplot as plt

from rocqipath.core.logging import logger
from rocqipath.core.output import OutputLayout
from rocqipath.utils import (
    detect_wsi_format,
    find_hne_ihc_pairs_by_suffix,
    list_wsi_files,
)

try:
    from rocqipath.registration.registrar import WSIRegistrar

    _HAS_REGISTRATION = True
except ImportError as _registration_error:
    WSIRegistrar = None  # type: ignore[assignment,misc]
    _HAS_REGISTRATION = False
    _REGISTRATION_IMPORT_ERROR = _registration_error

_HAS_GRID_PLOTTING = True


def _require_grid_dependencies() -> None:
    """Raise a focused error when registration or plotting is unavailable."""
    if _HAS_REGISTRATION:
        return
    raise RuntimeError(
        "Grid-map dependencies are unavailable. Install 'rocqipath[orb,viz]'. "
        f"Import error: {_REGISTRATION_IMPORT_ERROR}"
    )


def plot_selector_map(thumb_img, valid_ids, rows, cols, output_path=None, *, show=True):
    """Overlay a coloured tissue-selection grid on a slide thumbnail.

    Parameters
    ----------
    thumb_img : PIL.Image.Image
        Slide thumbnail in its own pixel coordinate space.
    valid_ids : container of int
        Row-major grid indices to highlight as tissue.
    rows : int
        Number of uniform grid rows.
    cols : int
        Number of uniform grid columns.
    output_path : str, optional
        Figure destination. No file is written when omitted.
    show : bool, optional
        Display the figure non-blockingly before closing it.

    Returns
    -------
    None
        The function writes or displays the figure through side effects.

    Notes
    -----
    Grid spans are floating-point thumbnail pixels: ``width / cols`` and
    ``height / rows``. Highlighted cells keep the historical green fill,
    red index labels, and one-second interactive pause.

    Examples
    --------
    >>> from PIL import Image
    >>> plot_selector_map(Image.new("RGB", (100, 100)), {0}, 2, 2, show=False)
    """
    fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
    ax.imshow(thumb_img)
    ax.set_title("Grid Map - Green boxes have tissue content")

    t_w, t_h = thumb_img.size
    sx = t_w / cols
    sy = t_h / rows

    count = 0
    for r in range(rows):
        for c in range(cols):
            if count in valid_ids:
                tx, ty = c * sx, r * sy
                rect = patches.Rectangle(
                    (tx, ty), sx, sy, lw=1, edgecolor="#00FF00", facecolor="green", alpha=0.2
                )
                ax.add_patch(rect)
                ax.text(tx + 5, ty + 20, f"#{count}", color="red", fontsize=8, weight="bold")
            count += 1

    plt.axis("off")
    if output_path:
        plt.savefig(output_path)
        logger.info("Grid map saved to %s", output_path)

    if show:
        plt.show(block=False)
        plt.pause(1)
    plt.close(fig)


def _build_registrar_config(
    *,
    output_dir: str,
    patch_size: int = 512,
    grid_density: int = 20,
) -> dict:
    """Construct the historical WSIRegistrar configuration mapping."""
    return {
        "base_output_dir": output_dir,
        "patch_size": patch_size,
        "grid_density": grid_density,
    }


def generate_single_grid_map_for_slide(
    wsi_path: str,
    output_dir: str,
    cfg: dict,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Generate and save a tissue grid-map PNG for a single slide."""
    wsi_format = detect_wsi_format(wsi_path)
    if wsi_format is None:
        return False, None, "Unsupported WSI format"
    if not os.path.isfile(wsi_path):
        return False, None, "WSI file not found"
    _require_grid_dependencies()
    os.makedirs(output_dir, exist_ok=True)

    registrar = WSIRegistrar(wsi_path, None, cfg)
    try:
        thumb, valid_grids = registrar.generate_grid_map()
        if thumb is None:
            return False, None, "Thumbnail generation failed"
        if not valid_grids:
            return False, None, "No valid tissue grids found"

        base_name = os.path.splitext(os.path.basename(wsi_path))[0]
        map_path = os.path.join(output_dir, f"{base_name}_grid_map.png")
        plot_selector_map(
            thumb,
            valid_grids,
            cfg["grid_density"],
            cfg["grid_density"],
            map_path,
            show=False,
        )
        return True, map_path, None
    except Exception as exc:
        return False, None, str(exc)
    finally:
        try:
            registrar.close()
        except Exception:
            pass


def save_paired_grid_map_figure(
    hne_map_path: str,
    ihc_map_path: str,
    save_path: str,
    hne_title: str,
    ihc_title: str,
) -> None:
    """Render and save a side-by-side H&E/IHC grid-map figure at 300 DPI."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    hne_img = Image.open(hne_map_path).convert("RGB")
    ihc_img = Image.open(ihc_map_path).convert("RGB")

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    axes[0].imshow(hne_img)
    axes[0].set_title(hne_title, fontsize=12)
    axes[0].axis("off")
    axes[1].imshow(ihc_img)
    axes[1].set_title(ihc_title, fontsize=12)
    axes[1].axis("off")
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def export_grid_map(
    wsi_path: str,
    output_dir: str,
    *,
    grid_density: int = 20,
) -> Optional[str]:
    """Generate and save a tissue grid-map PNG for one WSI."""
    _require_grid_dependencies()
    os.makedirs(output_dir, exist_ok=True)
    cfg = _build_registrar_config(
        output_dir=output_dir,
        grid_density=grid_density,
    )
    success, map_path, reason = generate_single_grid_map_for_slide(
        wsi_path,
        output_dir,
        cfg,
    )
    if not success:
        logger.warning(f"Grid map failed for {wsi_path}: {reason}")
        return None
    return map_path


def export_paired_grid_maps(
    input_dir: str,
    output_dir: str,
    biomarker: str,
    *,
    grid_density: int = 20,
) -> dict:
    """Generate side-by-side H&E/IHC grid maps for suffix-paired slides."""
    _require_grid_dependencies()
    layout = OutputLayout(output_dir)
    single_dir = tempfile.mkdtemp(prefix="rocqipath_grid_maps_")
    cfg = _build_registrar_config(
        output_dir=output_dir,
        grid_density=grid_density,
    )

    files = list_wsi_files(input_dir)
    pairs = find_hne_ihc_pairs_by_suffix(files, biomarker)
    if not pairs:
        logger.warning(f"No H&E / {biomarker} suffix-pairs found in {input_dir}")
        shutil.rmtree(single_dir, ignore_errors=True)
        return {"saved": 0, "skipped": 0}

    saved = skipped = 0
    for pair in pairs:
        suffix = pair["suffix"]
        hne_path = os.path.join(input_dir, pair["hne"])
        ihc_path = os.path.join(input_dir, pair["ihc"])

        hne_ok, hne_map, hne_reason = generate_single_grid_map_for_slide(
            hne_path,
            single_dir,
            cfg,
        )
        if not hne_ok:
            logger.warning(f"SKIP {suffix}: H&E grid map failed — {hne_reason}")
            skipped += 1
            continue

        ihc_ok, ihc_map, ihc_reason = generate_single_grid_map_for_slide(
            ihc_path,
            single_dir,
            cfg,
        )
        if not ihc_ok:
            logger.warning(f"SKIP {suffix}: IHC grid map failed — {ihc_reason}")
            skipped += 1
            continue

        pair_dir = layout.item_dir("visualization", f"{suffix}_{biomarker}")
        save_path = str(pair_dir / f"{suffix}_{biomarker}_paired_grid_map.png")
        try:
            save_paired_grid_map_figure(
                hne_map_path=hne_map,
                ihc_map_path=ihc_map,
                save_path=save_path,
                hne_title=f"H&E ({suffix})",
                ihc_title=f"{biomarker} ({suffix})",
            )
            logger.info(f"SAVED: {save_path}")
            saved += 1
        except Exception as exc:
            logger.warning(f"SKIP {suffix}: figure save failed — {exc}")
            skipped += 1

    shutil.rmtree(single_dir, ignore_errors=True)
    logger.info(f"export_paired_grid_maps: saved={saved}  skipped={skipped}")
    return {"saved": saved, "skipped": skipped}


__all__ = [
    "export_grid_map",
    "export_paired_grid_maps",
    "generate_single_grid_map_for_slide",
    "plot_selector_map",
    "save_paired_grid_map_figure",
]
