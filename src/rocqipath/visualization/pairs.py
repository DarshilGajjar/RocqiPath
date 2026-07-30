"""Patch-pair viewing entry points."""

from __future__ import annotations

import os
import random
from typing import Union

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

from rocqipath.core.logging import logger
from rocqipath.utils import discover_patch_pairs


def view_pairs(grid_folder, num_to_show="all"):
    """Display discovered H&E and IHC patch pairs for visual QC.

    Parameters
    ----------
    grid_folder : str
        Flat per-case output directory or a legacy directory containing
        ``HnE`` and ``IHC`` subfolders.
    num_to_show : int or {"all"}, optional
        Number of pairs to display. Integer selection uses random
        sampling without replacement.

    Returns
    -------
    None
        One blocking matplotlib window is shown per selected pair.

    Notes
    -----
    Pairs are discovered from the case manifest first and supported
    filename conventions second. A corrupt pair is reported and skipped
    without aborting later figures.
    """
    root = os.path.abspath(grid_folder)
    pairs = discover_patch_pairs(root)
    total = len(pairs)

    if total == 0:
        logger.warning("No paired patches found under {}", root)
        return

    if num_to_show == "all":
        indices = range(total)
    else:
        indices = sorted(random.sample(range(total), min(int(num_to_show), total)))

    logger.info("Visualizing {} pairs from {}", len(indices), os.path.basename(grid_folder))

    for idx in indices:
        path_a, path_b, f_name = pairs[idx]
        try:
            img_a = mpimg.imread(path_a)
            img_b = mpimg.imread(path_b)

            fig, axes = plt.subplots(1, 2, figsize=(12, 6))
            axes[0].imshow(img_a)
            axes[0].set_title(f"H&E (Ref): {f_name}")
            axes[0].axis("off")

            axes[1].imshow(img_b)
            axes[1].set_title(f"IHC (Target): {f_name}")
            axes[1].axis("off")

            plt.tight_layout()
            plt.show()
        except Exception as e:
            print(f"Error showing pair {f_name}: {e}")


def visualize_patch_pairs(
    grid_folder: str,
    num_to_show: Union[int, str] = "all",
) -> None:
    """Visualize extracted H&E/IHC patch pairs side by side."""
    view_pairs(grid_folder, num_to_show=num_to_show)


__all__ = ["view_pairs", "visualize_patch_pairs"]
