"""Small synthetic fixtures shared by integration-style regression tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.fixtures import make_patch_dataset, make_registration_tree, make_tissue_rgb


@pytest.fixture
def synthetic_registration_tree(tmp_path: Path) -> dict[str, Path]:
    """One complete H&E/CD8 pair in the public alignment layout."""
    return make_registration_tree(tmp_path / "registration")


@pytest.fixture
def synthetic_patch_dataset(tmp_path: Path) -> dict[str, Path]:
    """One aligned pair whose four 4x4 windows are all tissue."""
    return make_patch_dataset(tmp_path)


@pytest.fixture
def synthetic_tissue_rgb() -> np.ndarray:
    """A 10x10 RGB tile with exactly 25 tissue pixels."""
    return make_tissue_rgb()
