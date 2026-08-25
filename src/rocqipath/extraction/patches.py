"""Single-slide patch extraction utilities."""

from __future__ import annotations

import os
from typing import List, Optional

from rocqipath.config import PatchExtractionConfig
from rocqipath.core.logging import logger
from rocqipath.extraction.patch_pipeline import run_patch_extraction
from rocqipath.extraction.reversible import ReversiblePatchExtractor
from rocqipath.utils import list_wsi_files

try:
    from rocqipath.registration.registrar import WSIRegistrar
    from rocqipath.visualization.grids import plot_selector_map

    _HAS_PATCH_DEPENDENCIES = True
except ImportError as _dependency_error:
    WSIRegistrar = None  # type: ignore[assignment,misc]
    plot_selector_map = None  # type: ignore[assignment]
    _HAS_PATCH_DEPENDENCIES = False
    _PATCH_IMPORT_ERROR = _dependency_error


def _require_patch_dependencies() -> None:
    """Raise when registration or grid plotting is unavailable."""
    if not _HAS_PATCH_DEPENDENCIES:
        raise RuntimeError(
            "Grid-map dependencies are unavailable. Install "
            f"'rocqipath[orb,viz]'. Import error: {_PATCH_IMPORT_ERROR}"
        )


def extract_patches_single(
    input_dir: str,
    output_dir: str,
    *,
    wsi_files: Optional[List[str]] = None,
    patch_size: int = 512,
    grid_density: int = 20,
    grid_ids: Optional[List[int]] = None,
) -> None:
    """Extract tissue-grid patches from unpaired reference slides.

    Parameters
    ----------
    input_dir : str
        Directory containing input WSIs.
    output_dir : str
        Root directory used by :class:`WSIRegistrar` and
        :class:`~rocqipath.core.output.OutputLayout`.
    wsi_files : list of str, optional
        Basenames to process. Defaults to every discovered WSI.
    patch_size : int, optional
        Square patch edge in pixels at the configured target magnification.
    grid_density : int, optional
        Number of rows and columns in the uniform selector grid.
    grid_ids : list of int, optional
        Row-major grid indices to extract. Defaults to all tissue cells.

    Returns
    -------
    None
        Patch images and grid maps are written as side effects.

    Raises
    ------
    RuntimeError
        If registration or visualization dependencies are unavailable.

    Notes
    -----
    A requested grid without tissue is skipped. Failures are logged per
    slide so later slides continue processing.
    """
    _require_patch_dependencies()
    os.makedirs(output_dir, exist_ok=True)
    cfg = {
        "base_output_dir": output_dir,
        "patch_size": patch_size,
        "grid_density": grid_density,
    }

    all_files = list_wsi_files(input_dir)
    files_to_process = wsi_files if wsi_files else all_files
    if not files_to_process:
        logger.warning(f"No WSI files found in {input_dir}")
        return

    for wsi_file in files_to_process:
        wsi_path = os.path.join(input_dir, wsi_file)
        registrar = WSIRegistrar(wsi_path, None, cfg)
        try:
            thumb, valid_grids = registrar.generate_grid_map()
            target_grids = grid_ids if grid_ids is not None else valid_grids
            map_path = os.path.join(registrar.output_dir, "grid_map.png")
            plot_selector_map(
                thumb,
                valid_grids,
                grid_density,
                grid_density,
                map_path,
            )

            for grid_id in target_grids:
                if grid_id not in valid_grids:
                    logger.warning(f"{wsi_file}: grid {grid_id} is not tissue — skipping")
                    continue
                count = registrar.extract_single_patch(grid_id)
                logger.info(f"{wsi_file}: grid {grid_id} → {count} patches")
        except Exception as exc:
            logger.error(f"Failed for {wsi_path}: {exc}")
        finally:
            try:
                registrar.close()
            except Exception:
                pass


__all__ = [
    "PatchExtractionConfig",
    "ReversiblePatchExtractor",
    "extract_patches_single",
    "run_patch_extraction",
]
