"""Unit coverage for the consolidated tissue primitives."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from rocqipath.core.tissue import (
    brightness_saturation_is_tissue,
    is_tissue,
    pil_intensity_fraction,
    pil_is_tissue,
    tissue_fraction,
    tissue_mask,
)


def test_mean_intensity_mask_and_inclusive_gate() -> None:
    """Keep the historical 235 cutoff and inclusive fraction comparison."""
    rgb = np.full((2, 2, 3), 255, dtype=np.uint8)
    rgb[0] = 234

    np.testing.assert_array_equal(
        tissue_mask(rgb),
        np.array([[True, True], [False, False]]),
    )
    assert tissue_fraction(rgb) == 0.5
    assert is_tissue(rgb, threshold=0.5) is True
    assert is_tissue(rgb, threshold=0.5001) is False


def test_pil_fraction_uses_strict_pixel_cutoff() -> None:
    """Distinguish the strict pixel cutoff from the inclusive patch gate."""
    pixels = np.array([[234, 235], [255, 0]], dtype=np.uint8)
    image = Image.fromarray(pixels, mode="L")

    assert pil_intensity_fraction(image, intensity_threshold=235) == 0.5
    assert pil_is_tissue(image, threshold=0.5, intensity_threshold=235) is True


def test_brightness_saturation_mean_gate_boundaries() -> None:
    """Pin both inclusive boundaries used by comparison ROI selection."""
    assert brightness_saturation_is_tissue(220 / 255, 0.05) is True
    assert brightness_saturation_is_tissue((220 / 255) + 1e-8, 0.05) is False
    assert brightness_saturation_is_tissue(220 / 255, 0.049) is False


def test_unknown_tissue_method_is_rejected() -> None:
    """Report invalid consolidation modes instead of silently changing methods."""
    rgb = np.zeros((1, 1, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="Unknown tissue-mask method"):
        tissue_mask(rgb, method="unknown")
