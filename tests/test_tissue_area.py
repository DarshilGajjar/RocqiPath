"""Synthetic-mask regression tests for tissue-area denominators."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

import rocqipath.analysis.cell_counting as cell_counting
from rocqipath.analysis.cell_counting import PositiveCellCounter


def test_tissue_mask_counts_only_non_background_pixels(synthetic_tissue_rgb):
    counter = object.__new__(PositiveCellCounter)
    counter.tissue_threshold = 0.1

    mask = counter._tissue_mask(synthetic_tissue_rgb)

    assert mask.dtype == np.bool_
    assert int(mask.sum()) == 25
    assert counter._is_tissue(synthetic_tissue_rgb) is True


def test_count_slide_uses_mask_pixels_for_area(tmp_path: Path, synthetic_tissue_rgb, monkeypatch):
    class FakeReader:
        def __init__(self, _path):
            self.target_dimensions = (10, 10)
            self.properties = {"openslide.mpp-x": "1000", "openslide.mpp-y": "1000"}

        def configure_magnification(self, *_args):
            return SimpleNamespace(level0_per_target_pixel=1.0)

        def read_at_magnification(self, _location, _size):
            return Image.fromarray(synthetic_tissue_rgb, mode="RGB")

        def close(self):
            pass

    monkeypatch.setattr(cell_counting, "_SlideReader", FakeReader)
    counter = PositiveCellCounter(
        {
            "patch_size": 10,
            "tissue_threshold": 0.1,
            "output_dir": str(tmp_path),
            "min_cell_area": 1,
        }
    )
    monkeypatch.setattr(counter, "_count_patch", lambda _rgb: (5,))

    result = counter.count_slide("synthetic.tif")

    assert result["tissue_pixels"] == 25
    assert result["tissue_area_mm2"] == 25.0
    assert result["density_per_mm2"] == 0.2
    assert result["tissue_area_method"] == "pixel_mask"
