"""Figure writers for multi-marker IHC overlays."""

from __future__ import annotations

from typing import Dict

import matplotlib.pyplot as plt
import numpy as np

from rocqipath.config import IHCOverlayConfig, OverlayCombo


def _save_composite_figure(composite: np.ndarray, out_path: str, cfg: IHCOverlayConfig) -> None:
    """Save a coloured composite image to disk as a borderless figure.

    Parameters
    ----------
    composite : numpy.ndarray
        ``(H, W, 3)`` RGB composite, as returned by
        :func:`_build_composite`.
    out_path : str
        Destination file path.
    cfg : IHCOverlayConfig
        Supplies ``dpi`` and ``show_plot``.

    Notes
    -----
    Saved with no axes, no padding, and a tight bounding box, so the
    output file is just the image itself at the requested DPI — suitable
    for direct use in a figure/slide rather than a labelled plot.
    """
    fig, ax = plt.subplots(figsize=(6, 6), dpi=cfg.dpi)
    ax.imshow(composite)
    ax.axis("off")
    fig.tight_layout(pad=0)
    fig.savefig(out_path, dpi=cfg.dpi, bbox_inches="tight", pad_inches=0)
    if cfg.show_plot:
        plt.show()
    plt.close(fig)


def _save_grid_figure(
    images: Dict[str, np.ndarray],
    masks: Dict[str, np.ndarray],
    composite: np.ndarray,
    combo: OverlayCombo,
    cfg: IHCOverlayConfig,
    out_path: str,
) -> None:
    """Save a multi-panel figure: one binary mask per marker, plus the composite.

    Parameters
    ----------
    images : dict of str to numpy.ndarray
        Original RGB patches, keyed by marker key (unused directly here,
        accepted for signature symmetry with :func:`_build_composite` and
        potential future panel types).
    masks : dict of str to numpy.ndarray
        Boolean detection masks, keyed by marker key.
    composite : numpy.ndarray
        The already-built composite (from :func:`_build_composite`) shown
        as the final panel.
    combo : OverlayCombo
        Determines panel order: base marker first, then each overlay in
        list order, then the composite.
    cfg : IHCOverlayConfig
        Supplies ``dpi``, ``show_plot``, and marker labels (via
        ``cfg.markers[...].label``) used as panel titles.
    out_path : str
        Destination file path.

    Notes
    -----
    Each marker panel renders its mask via
    ``ax.imshow(mask, cmap="gray")`` — white where detected, black
    elsewhere — titled with that marker's
    :attr:`~MarkerProfile.label`. The final panel is titled
    ``"Composite"``.
    """
    panel_keys = [combo.base] + list(combo.overlays)
    n = len(panel_keys) + 1
    fig, axes = plt.subplots(1, n, figsize=(4 * n, 4), dpi=cfg.dpi)
    if n == 1:
        axes = [axes]
    for ax, mk in zip(axes, panel_keys):
        ax.imshow(masks[mk], cmap="gray")
        ax.set_title(cfg.markers[mk].label)
        ax.axis("off")
    axes[-1].imshow(composite)
    axes[-1].set_title("Composite")
    axes[-1].axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=cfg.dpi, bbox_inches="tight")
    if cfg.show_plot:
        plt.show()
    plt.close(fig)
