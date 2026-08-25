"""Registration grid selection and aligned patch extraction."""

from __future__ import annotations

import os
from typing import Tuple

import numpy as np
from PIL import Image

from rocqipath.core.logging import logger
from rocqipath.core.magnification import MagnificationPlan


def _check_patch_grid_viability(self) -> None:
    """Warn when the patch grid can never yield a patch.

    ``extract_patch_pair`` skips any patch that would cross a grid-cell
    boundary, so when a cell is narrower than ``patch_size`` every grid
    returns zero patches -- silently, with no error.  At 1x on a 20x slide
    with grid_density=10 the cell is ~40 px against a 512 px patch.
    """
    grid = self.config.get("grid_density")
    patch = self.config.get("patch_size")
    if not grid or not patch:
        return
    cell_w = self.target_w / grid
    cell_h = self.target_h / grid
    if min(cell_w, cell_h) < patch:
        logger.warning(
            f"[GRID] Grid cell is {cell_w:.0f}x{cell_h:.0f} px but patch_size "
            f"is {patch} — patch extraction would yield 0 patches per grid. "
            f"Raise target_magnification, lower grid_density, or lower "
            f"patch_size."
        )


def generate_grid_map(self) -> Tuple[Image.Image, list]:
    """Identify tissue cells in a uniform reference-slide grid.

    Strategy
    ────────
    A low-resolution thumbnail is generated from the reference slide.
    Each grid cell is classified as "tissue" if more than 5 % of its
    pixels are darker than 230 in greyscale (i.e. not glass background).

    Returns
    -------
    ───────
    map_thumb : PIL.Image
        Thumbnail image saved to ``<output_dir>/grid_map.png``.
    valid_grids : list[int]
        Flat grid indices (row-major) of tissue-containing cells.
    """
    rows = cols = self.config["grid_density"]

    # Build a thumbnail that preserves the slide aspect ratio
    thumb_h = 1000
    thumb_w = int(thumb_h * (self.w / self.h))
    self.map_thumb = self.slide_ref.get_thumbnail((thumb_w, thumb_h))

    # Binary tissue mask: True where pixel is darker than 230 (tissue)
    mask = np.array(self.map_thumb.convert("L")) < 230

    step_y = mask.shape[0] / rows
    step_x = mask.shape[1] / cols
    self.valid_grids: list = []

    for idx in range(rows * cols):
        r, c = divmod(idx, cols)
        y1, y2 = int(r * step_y), int((r + 1) * step_y)
        x1, x2 = int(c * step_x), int((c + 1) * step_x)
        region = mask[y1:y2, x1:x2]
        tissue_fraction = np.count_nonzero(region) / region.size if region.size > 0 else 0
        if tissue_fraction > 0.05:
            self.valid_grids.append(idx)

    # self.map_thumb.save(os.path.join(self.output_dir, "grid_map.png"))
    logger.info(f"[GRID] {len(self.valid_grids)} tissue grids out of {rows * cols} total.")
    return self.map_thumb, self.valid_grids


def extract_patch_pair(self, grid_id: int) -> int:
    """
    Extract spatially aligned H&E / IHC patch pairs from a single grid cell.

    For each non-background patch in the reference (H&E) slide, the
    corresponding IHC location is computed via ``_transform_coords()``
    and both patches are saved as matching PNG files.

    Reference and moving PNGs are written together inside the case output
    directory. Filenames contain grid, patch, and channel identifiers.

    Parameters
    ----------
    ──────────
    grid_id : int
        Flat (row-major) grid index, as returned by ``generate_grid_map()``.

    Returns
    -------
    ───────
    count : int
        Number of patch pairs successfully saved.
    """
    rows = cols = self.config["grid_density"]
    patch_size = self.config["patch_size"]
    ref_stem = os.path.splitext(self.ref_name)[0]

    # Compute the base-level pixel extent of this grid cell
    real_sx = self.target_w / cols
    real_sy = self.target_h / rows
    r, c = divmod(grid_id, cols)
    min_x, min_y = int(c * real_sx), int(r * real_sy)
    max_x, max_y = int(min_x + real_sx), int(min_y + real_sy)

    count = 0
    for y in range(min_y, max_y, patch_size):
        for x in range(min_x, max_x, patch_size):
            # Skip incomplete border patches (avoids partial-tissue artefacts)
            if x + patch_size > max_x or y + patch_size > max_y:
                continue

            # Read H&E patch
            x0, y0 = self.ref_magnification_plan.target_to_level0((x, y))
            patch_ref = self._read_exact_magnification(
                self.slide_ref,
                self.ref_magnification_plan,
                (x0, y0),
                (patch_size, patch_size),
            ).convert("RGB")

            # Skip near-white (glass background) patches — mean > 240 ≈ background
            if np.asarray(patch_ref).mean() > 240:
                continue

            # Map H&E coordinates → IHC coordinates
            tx, ty = self._transform_coords(x0, y0)
            if tx is None:
                continue

            # Read IHC patch at the mapped location
            try:
                patch_tgt = self._read_exact_magnification(
                    self.slide_tgt,
                    self.tgt_magnification_plan,
                    (tx, ty),
                    (patch_size, patch_size),
                ).convert("RGB")
            except Exception:
                continue

            # Skip IHC patch if it is also background
            if np.asarray(patch_tgt).mean() > 240:
                continue

            # Save matched pair
            count += 1
            stem = f"{ref_stem}_grid{grid_id:03d}_patch{count:04d}"
            patch_ref.save(os.path.join(self.output_dir, f"{stem}_reference.png"))
            patch_tgt.save(os.path.join(self.output_dir, f"{stem}_moving.png"))

    return count


def extract_single_patch(self, grid_id: int) -> int:
    """
    Extract patches from the reference slide only (no IHC target).

    Useful for reference-only mode or when only H&E patches are needed.
    Patches are saved directly inside the case output directory with the
    grid identifier encoded in each filename.

    Parameters
    ----------
    ──────────
    grid_id : int
        Flat (row-major) grid index.

    Returns
    -------
    ───────
    count : int
        Number of patches saved.
    """
    rows = cols = self.config["grid_density"]
    patch_size = self.config["patch_size"]
    ref_stem = os.path.splitext(self.ref_name)[0]

    real_sx = self.target_w / cols
    real_sy = self.target_h / rows
    r, c = divmod(grid_id, cols)
    min_x, min_y = int(c * real_sx), int(r * real_sy)
    max_x, max_y = int(min_x + real_sx), int(min_y + real_sy)

    count = 0
    for y in range(min_y, max_y, patch_size):
        for x in range(min_x, max_x, patch_size):
            if x + patch_size > max_x or y + patch_size > max_y:
                continue
            location0 = self.ref_magnification_plan.target_to_level0((x, y))
            patch = self._read_exact_magnification(
                self.slide_ref,
                self.ref_magnification_plan,
                location0,
                (patch_size, patch_size),
            ).convert("RGB")
            if np.asarray(patch).mean() > 240:
                continue
            count += 1
            patch.save(
                os.path.join(
                    self.output_dir,
                    f"{ref_stem}_grid{grid_id:03d}_patch{count:04d}.png",
                )
            )

    return count


@staticmethod
def _read_exact_magnification(
    slide: object,
    plan: MagnificationPlan,
    location0: Tuple[int, int],
    output_size: Tuple[int, int],
) -> Image.Image:
    """Read a level-0 location and return pixels at the plan's exact zoom."""
    native_size = plan.native_read_size(output_size)
    image = slide.read_region(location0, plan.level, native_size)
    if image.size != output_size:
        image = image.resize(output_size, Image.Resampling.LANCZOS)
    return image
