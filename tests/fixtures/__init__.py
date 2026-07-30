"""Synthetic, scanner-free fixtures for RocqiPath tests."""

from .synthetic import (
    make_patch_dataset,
    make_registration_tree,
    make_tissue_rgb,
    save_rgb_tiff,
)

__all__ = [
    "make_patch_dataset",
    "make_registration_tree",
    "make_tissue_rgb",
    "save_rgb_tiff",
]
