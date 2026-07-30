"""Generate deterministic RGB arrays and fake whole-slide directory trees."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def save_rgb_tiff(path: Path, rgb: np.ndarray) -> None:
    """Save a small RGB array as an ordinary TIFF usable by fallback readers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(path, format="TIFF")


def make_registration_tree(root: Path) -> dict[str, Path]:
    """Create one complete H&E/CD8 pair in the generalized alignment layout."""
    rgb = np.full((8, 8, 3), 160, dtype=np.uint8)
    reference = root / "CD8" / "he" / "case01_HE.tif"
    moving = root / "CD8" / "cd8" / "case01_CD8.tif"
    save_rgb_tiff(reference, rgb)
    save_rgb_tiff(moving, rgb)
    return {
        "root": root,
        "reference": reference,
        "moving": moving,
        "output": root.parent / "aligned",
    }


def make_patch_dataset(root: Path) -> dict[str, Path]:
    """Create one aligned pair whose four 4x4 windows are all tissue."""
    reference_root = root / "reference"
    aligned_root = root / "aligned"
    reference = reference_root / "Sample_0001_he.tif"
    target = aligned_root / "CD8" / "Sample_0001_he" / "aligned_cd8.ome.tiff"
    save_rgb_tiff(reference, np.full((8, 8, 3), (130, 80, 70), dtype=np.uint8))
    save_rgb_tiff(target, np.full((8, 8, 3), (115, 75, 60), dtype=np.uint8))
    return {
        "reference_root": reference_root,
        "aligned_root": aligned_root,
        "reference": reference,
        "target": target,
        "output": root / "patch_output",
    }


def make_tissue_rgb() -> np.ndarray:
    """Create a 10x10 RGB tile with exactly 25 non-background pixels."""
    rgb = np.full((10, 10, 3), 255, dtype=np.uint8)
    rgb[:5, :5] = (100, 80, 60)
    return rgb
