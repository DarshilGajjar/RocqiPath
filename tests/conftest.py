"""Small synthetic fixtures shared by integration-style regression tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image


def _save_rgb_tiff(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(path, format="TIFF")


@pytest.fixture
def synthetic_registration_tree(tmp_path: Path) -> dict[str, Path]:
    """One complete H&E/CD8 pair in the public alignment layout."""
    root = tmp_path / "registration"
    rgb = np.full((8, 8, 3), 160, dtype=np.uint8)
    he = root / "CD8" / "he" / "case01_HE.tif"
    ihc = root / "CD8" / "ihc" / "case01_CD8.tif"
    _save_rgb_tiff(he, rgb)
    _save_rgb_tiff(ihc, rgb)
    return {"root": root, "he": he, "ihc": ihc, "output": tmp_path / "aligned"}


@pytest.fixture
def synthetic_patch_dataset(tmp_path: Path) -> dict[str, Path]:
    """One aligned pair whose four 4x4 windows are all tissue."""
    reference_root = tmp_path / "reference"
    aligned_root = tmp_path / "aligned"
    reference = reference_root / "Sample_0001_he.tif"
    target = aligned_root / "CD8" / "Sample_0001_he" / "aligned_cd8.ome.tiff"
    _save_rgb_tiff(reference, np.full((8, 8, 3), (130, 80, 70), dtype=np.uint8))
    _save_rgb_tiff(target, np.full((8, 8, 3), (115, 75, 60), dtype=np.uint8))
    return {
        "reference_root": reference_root,
        "aligned_root": aligned_root,
        "reference": reference,
        "target": target,
        "output": tmp_path / "patch_output",
    }


@pytest.fixture
def synthetic_tissue_rgb() -> np.ndarray:
    """A 10x10 RGB tile with exactly 25 tissue pixels."""
    rgb = np.full((10, 10, 3), 255, dtype=np.uint8)
    rgb[:5, :5] = (100, 80, 60)
    return rgb
