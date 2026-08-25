#!/usr/bin/env python3
"""Create publication-quality side-by-side WSI comparison figures.

Generates high-resolution ground-truth-vs-prediction (or any two-image)
comparison figures with scale bars, colourblind-safe annotations, and
professional figure formatting — suitable for papers, posters, and
reports, as opposed to :mod:`rocqipath.visualization.visualization`'s
quick exploratory QC plots.

Also runnable as a standalone script::

    rocqipath compare --help

Uses the package's standard-library logging configuration and remains usable
through the unified command-line interface.

WSI Visualization Module for RocqiPath — PUBLICATION-QUALITY EDITION
Generates high-resolution side-by-side comparisons with scale bars,
colorblind-safe annotations, and professional figure formatting.
"""

import shutil

from PIL import Image, PngImagePlugin

from rocqipath.visualization.comparison_workflow import (
    VALID_REGIONS as VALID_REGIONS,
    _add_scale_bar as _add_scale_bar,
    _region_bbox as _region_bbox,
    _tissue_fraction as _tissue_fraction,
    visualize_side_by_side as visualize_side_by_side,
)
from rocqipath.visualization.roi import _is_tissue as _is_tissue

# WARNING: raising this reduces Pillow's protection against malicious decompression bombs.
PngImagePlugin.MAX_TEXT_CHUNK = 64 * 1024 * 1024
# Essential for loading massive WSIs without raising DecompressionBombError
Image.MAX_IMAGE_PIXELS = None


# ============================================================================
# PUBLICATION-QUALITY COLOR PALETTES
# ============================================================================
COLORBLIND_SAFE_PALETTE = [
    "#0173B2",  # Blue
    "#DE8F05",  # Orange
    "#CC78BC",  # Magenta
    "#CA9161",  # Brown
    "#56B4E9",  # Light blue
    "#029E73",  # Green
    "#ECE133",  # Yellow
    "#56B4E9",  # Cyan
    "#F8766D",  # Red
    "#00BA38",  # Bright green
]

# Publication-grade grayscale for structure/labels
GRAYSCALE_PALETTE = [
    "#000000",  # Black (text, main stroke)
    "#404040",  # Dark gray (secondary)
    "#808080",  # Medium gray (tertiary)
    "#C0C0C0",  # Light gray (borders)
    "#FFFFFF",  # White (background)
]


# ============================================================================
# PLAIN-TEXT BANNER
# ============================================================================
def _build_banner(tool_name: str, subtitle: str = "") -> str:
    """Build a centred, boxed ASCII banner string for startup logging.

    Parameters
    ----------
    tool_name : str
        Title shown on the banner's first content line.
    subtitle : str, optional
        Optional second content line (e.g. a mode or version string).
        Omitted from the banner entirely when empty.

    Returns
    -------
    str
        A multi-line string: a box-drawing-character border surrounding
        ``tool_name``, ``subtitle`` (if given), and a fixed
        ``"Author: Darshil Gajjar"`` line — each line horizontally
        centred within the box, and the whole box horizontally centred
        within the current terminal width (detected via
        :func:`shutil.get_terminal_size`, falling back to 80 columns if
        that can't be determined). Prefixed and suffixed with a newline
        for spacing when printed.

    Notes
    -----
    The result is plain text suitable for either ``print`` or stdlib logging.
    """
    inner_width = 54
    lines = [
        "╔" + "═" * inner_width + "╗",
        "║" + tool_name.center(inner_width) + "║",
    ]
    if subtitle:
        lines.append("║" + subtitle.center(inner_width) + "║")
    lines.extend(
        [
            "║" + "Author: Darshil Gajjar".center(inner_width) + "║",
            "╚" + "═" * inner_width + "╝",
        ]
    )
    term_width = shutil.get_terminal_size(fallback=(80, 24)).columns
    return "\n" + "\n".join(line.center(term_width) for line in lines) + "\n"


# ============================================================================
# MANIFEST READER
# ============================================================================


# ============================================================================
# REGION HELPERS
# ============================================================================


# Minimum tissue coverage required for a named-region crop (0.0–1.0).
# 0.50 = reject any crop where > 50 % of pixels are background/glass.

# Search parameters: how far from the nominal anchor to hunt for tissue.

# Thumbnail size for fast tissue scoring during region search


# ============================================================================
# MICRONS-PER-PIXEL LOOKUP
# ============================================================================

# Physical pixel sizes calibrated from the WSI pipeline output.
# Calibration: at 20× the crop is 1000 px and spans 100 µm → 0.10 µm/px.
# All other zoom levels are derived by doubling/halving that value per octave.
# Override via --mpp if your scanner differs.

# Scale bar length (µm) chosen per zoom level so the bar is always a
# visually sensible fraction (~20-30%) of the field of view.


# ============================================================================
# MAIN VISUALIZATION FUNCTION — PUBLICATION QUALITY
# ============================================================================


# ============================================================================
# ENTRY POINT
# ============================================================================


def main(argv=None) -> int:
    """Delegate the historical comparison entry point to the unified CLI."""
    from rocqipath.cli.commands.compare import main as command_main

    return command_main(argv)
