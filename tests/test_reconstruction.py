"""Scanner-free checks for sparse patch reconstruction."""

import numpy as np

from rocqipath.extraction.reconstruction import _finalize_canvas


def test_overlap_averaging_keeps_uncovered_pixels_white():
    canvas = np.zeros((2, 2, 3), dtype=np.float32)
    counts = np.zeros((2, 2, 1), dtype=np.float32)
    canvas[0, 0] = (200, 100, 50)
    counts[0, 0] = 2
    result = _finalize_canvas(canvas, counts, overlapping=True)
    np.testing.assert_array_equal(result[0, 0], (100, 50, 25))
    assert np.all(result[1] == 255)
    assert np.all(result[0, 1] == 255)
