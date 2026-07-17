# -*- coding: utf-8 -*-
"""
roqcipath.config
=====================
Default configuration for all WSI processing pipelines.

All values can be overridden at runtime by passing an updated dict to
``WSIRegistrar`` or by constructing one of the typed config dataclasses
(e.g. ``CoreExtractionConfig``, ``TissueExtractionConfig``).
"""

DEFAULT_CONFIG: dict = {
    # ── I/O ──────────────────────────────────────────────────────────────────
    # Directories are None by default; the CLI will request them from the user.
    "base_input_dir":  None,
    "base_output_dir": None,

    # ── Patch extraction ─────────────────────────────────────────────────────
    "patch_size":          512,    # px — edge length of each extracted patch
    "target_magnification": 20.0,  # physical output zoom; scanner-independent
    "reference_source_magnification": None,  # metadata fallback for plain TIFF
    "target_source_magnification": None,
    "grid_density":        20,     # number of rows / cols in the grid map
    "downsample_factor":   64,     # coarse alignment speed-up factor

    # ── ORB registration fallback ─────────────────────────────────────────────
    "n_features":          5000,
    "ransac_threshold":    5.0,    # RANSAC reprojection threshold (full-res px)
    "orb_thumb_size":      1500,   # coarse thumbnail long-axis (px)
    "orb_refine_thumb_size": 3000, # refinement thumbnail long-axis (px)
    "orb_refine_enabled":  True,
    "orb_max_contours":    8,
    "orb_min_area_frac":   0.001,
    "orb_match_threshold": 1.4,
    "min_ncc_threshold":   0.25,

    # ── QC overlay ────────────────────────────────────────────────────────────
    "overlay_max_px": 4000,        # longest edge for VALIS QC overlay images
}
