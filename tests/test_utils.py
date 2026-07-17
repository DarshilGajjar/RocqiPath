"""Tests for WSI discovery and deterministic pairing."""

import tempfile
import unittest
from pathlib import Path

from roqcipath.utils import detect_wsi_format, find_hne_ihc_pairs_by_suffix, list_wsi_files


class UtilityTests(unittest.TestCase):
    def test_ome_extensions_are_detected_before_plain_tiff(self):
        self.assertEqual(detect_wsi_format("slide.ome.tiff"), ".ome.tiff")
        self.assertIsNone(detect_wsi_format("notes.txt"))

    def test_natural_file_sort(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("slide10.svs", "slide2.svs", "ignore.txt"):
                Path(root, name).touch()
            self.assertEqual(list_wsi_files(root), ["slide2.svs", "slide10.svs"])

    def test_suffix_pairing(self):
        files = ["TMA_HnE_mF1.tif", "TMA_CD8_mF1.tif", "TMA_HnE_mF2.tif"]
        self.assertEqual(
            find_hne_ihc_pairs_by_suffix(files, "CD8"),
            [{"suffix": "mF1", "hne": "TMA_HnE_mF1.tif", "ihc": "TMA_CD8_mF1.tif"}],
        )


if __name__ == "__main__":
    unittest.main()
