"""Regression coverage for extracted cell-counting report helpers."""

from __future__ import annotations

import matplotlib
import numpy as np

from rocqipath.analysis.reporting import _save_comparison_plot

matplotlib.use("Agg")


def test_comparison_plot_helper_accepts_stage_outputs(tmp_path) -> None:
    """Exercise the free helper with the tuple returned by ``_count_patch``."""
    rgb = np.full((8, 8, 3), 180, dtype=np.uint8)
    binary = np.zeros((8, 8), dtype=bool)
    labels = np.zeros((8, 8), dtype=np.int32)
    result = (0, binary, rgb.copy(), 42.0, labels)
    output = tmp_path / "comparison.png"

    _save_comparison_plot(
        rgb,
        result,
        rgb,
        result,
        patch_idx=1,
        x=0,
        y=0,
        save_path=str(output),
        dpi=72,
    )

    assert output.is_file()
