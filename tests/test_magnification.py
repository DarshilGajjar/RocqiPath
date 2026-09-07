"""Unit tests for scanner-independent magnification planning."""

import unittest
import json
import tempfile
from pathlib import Path

from PIL import Image
import numpy as np
import pytest

from rocqipath.core.magnification import (
    build_magnification_plan,
    objective_magnification_from_properties,
)
from rocqipath.core.slide import SlideReader


@pytest.mark.parametrize("location", [(20, 0), (0, 20), (-20, 0), (0, -20)])
def test_pil_reader_pads_regions_entirely_outside_image(tmp_path, location):
    path = tmp_path / "slide.png"
    Image.new("RGB", (8, 8), "red").save(path)
    with SlideReader(str(path)) as reader:
        reader.configure_magnification(20, 20)
        region = reader.read_at_magnification(location, (4, 4))
        assert region.size == (4, 4)
        assert np.all(np.asarray(region) == 255)


def test_pil_reader_preserves_partial_overlap(tmp_path):
    path = tmp_path / "slide.png"
    Image.new("RGB", (8, 8), "red").save(path)
    with SlideReader(str(path)) as reader:
        reader.configure_magnification(20, 20)
        region = np.asarray(reader.read_at_magnification((-2, -2), (4, 4)))
        assert np.all(region[:2] == 255)
        assert np.all(region[:, :2] == 255)
        assert np.all(region[2:, 2:] == (255, 0, 0, 255))


@pytest.mark.parametrize("payload", [[], None, "invalid", {"output_magnification": "inf"}])
def test_reader_ignores_invalid_manifest_and_uses_valid_fallback(tmp_path, payload):
    path = tmp_path / "slide.png"
    Image.new("RGB", (8, 8), "red").save(path)
    path.with_name("slide_manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"output_magnification": 40}), encoding="utf-8"
    )
    with SlideReader(str(path)) as reader:
        assert reader.configure_magnification(20).base_magnification == 40


class MagnificationPlanTests(unittest.TestCase):
    def test_80x_tma_selects_native_20x_level(self):
        plan = build_magnification_plan(80.0, 20.0, [1, 2, 4, 8, 16])
        self.assertEqual(plan.level, 2)
        self.assertEqual(plan.native_magnification, 20.0)
        self.assertEqual(plan.target_dimensions((8000, 4000)), (2000, 1000))
        self.assertEqual(plan.target_to_level0((100, 50)), (400, 200))
        self.assertEqual(plan.native_read_size((256, 256)), (256, 256))

    def test_nonmatching_level_reads_enough_pixels_before_resize(self):
        plan = build_magnification_plan(80.0, 20.0, [1, 2, 8])
        self.assertEqual(plan.level, 1)  # native 40x is as close as 10x; first wins
        self.assertEqual(plan.native_read_size((256, 256)), (512, 512))
        self.assertEqual(plan.resize_factor, 0.5)

    def test_20x_and_40x_slides_resolve_to_same_target(self):
        p20 = build_magnification_plan(20.0, 20.0, [1, 2, 4])
        p40 = build_magnification_plan(40.0, 20.0, [1, 2, 4])
        self.assertEqual(p20.native_magnification, 20.0)
        self.assertEqual(p40.native_magnification, 20.0)
        self.assertEqual(p20.target_dimensions((2000, 1000)), (2000, 1000))
        self.assertEqual(p40.target_dimensions((4000, 2000)), (2000, 1000))

    def test_metadata_and_explicit_fallback(self):
        self.assertEqual(
            objective_magnification_from_properties({"openslide.objective-power": "80"}),
            (80.0, "openslide.objective-power"),
        )
        self.assertEqual(
            objective_magnification_from_properties({}, fallback=40),
            (40.0, "fallback"),
        )
        with self.assertRaises(ValueError):
            objective_magnification_from_properties({})

    def test_invalid_upsampling_request_is_rejected(self):
        with self.assertRaises(ValueError):
            build_magnification_plan(20.0, 40.0, [1, 2])

    def test_plain_tiff_uses_sibling_manifest_and_resamples(self):
        with tempfile.TemporaryDirectory() as root:
            tif = Path(root, "region_001.tif")
            Image.new("RGB", (80, 40), "white").save(tif)
            tif.with_name("region_001_manifest.json").write_text(
                json.dumps({"output_magnification": 80.0}), encoding="utf-8"
            )
            reader = SlideReader(str(tif))
            try:
                reader.configure_magnification(20.0)
                self.assertEqual(reader.target_dimensions, (20, 10))
                self.assertEqual(
                    reader.read_at_magnification((0, 0), (10, 10)).size,
                    (10, 10),
                )
            finally:
                reader.close()


if __name__ == "__main__":
    unittest.main()
