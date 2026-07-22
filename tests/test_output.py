"""Tests for the standard module/item output hierarchy."""

import tempfile
import unittest
from pathlib import Path

from rocqipath.output import OutputLayout, safe_name


class OutputLayoutTests(unittest.TestCase):
    def test_module_item_layout_has_exactly_two_levels(self):
        with tempfile.TemporaryDirectory() as root:
            path = OutputLayout(root).item_dir("tissue_extraction", "Slide A")
            self.assertEqual(path, Path(root).resolve() / "tissue_extraction" / "Slide_A")
            self.assertTrue(path.is_dir())

    def test_unsafe_names_are_sanitized(self):
        self.assertEqual(safe_name("Patient 01 / H&E"), "Patient_01_H_E")
        with self.assertRaises(ValueError):
            safe_name("...")


if __name__ == "__main__":
    unittest.main()
