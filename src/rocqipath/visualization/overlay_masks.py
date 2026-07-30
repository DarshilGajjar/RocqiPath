"""Marker detection masks and deterministic overlay compositing."""

from __future__ import annotations

from typing import Dict

import cv2
import numpy as np

from rocqipath.config import IHCOverlayConfig, MarkerProfile, OverlayCombo


def _marker_mask(img_rgb: np.ndarray, profile: MarkerProfile) -> np.ndarray:
    """Compute a marker's binary detection mask for one RGB patch.

    Dispatches on ``profile.method`` (currently only ``"hsv"`` is
    implemented, enforced by :meth:`MarkerProfile.__post_init__`).

    Parameters
    ----------
    img_rgb : numpy.ndarray
        ``(H, W, 3)`` ``uint8`` RGB patch.
    profile : MarkerProfile
        Supplies ``hue_range`` and ``sat_min`` for the HSV gate.

    Returns
    -------
    numpy.ndarray
        A boolean ``(H, W)`` mask, ``True`` where this marker's signal
        was detected.

    Notes
    -----
    Same detection family as
    :meth:`rocqipath.analysis.cell_counting.PositiveCellCounter._brown_mask`
    combined with its OTSU-refinement step, generalized here so the hue
    range and saturation floor are per-marker configurable rather than
    fixed to a single "brown" gate:

    1. Convert to HSV and gate on ``hue_range``/``sat_min``.
    2. If fewer than 10 pixels pass the gate, return an all-``False``
       mask immediately (too little signal for a meaningful threshold).
    3. Invert the Value channel (so darker chromogen becomes brighter)
       and compute an OTSU threshold via :func:`cv2.threshold`,
       restricted to the gated pixels only.
    4. Return the intersection of the hue/saturation gate and the
       OTSU-thresholded inverted-Value mask.
    """
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lo, hi = profile.hue_range
    gate = (H >= lo) & (H <= hi) & (S >= profile.sat_min)

    if gate.sum() < 10:
        return np.zeros(img_rgb.shape[:2], dtype=bool)

    inv_val = cv2.bitwise_not(V)
    gated_vals = inv_val[gate]
    if gated_vals.max() == gated_vals.min():
        # Degenerate case: OTSU is undefined on a constant array — every
        # gated pixel is equally "positive", so keep the whole gate.
        return gate

    thresh_val, _ = cv2.threshold(gated_vals, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gate & (inv_val > thresh_val)


def _build_composite(
    images: Dict[str, np.ndarray],
    masks: Dict[str, np.ndarray],
    combo: OverlayCombo,
    cfg: IHCOverlayConfig,
) -> np.ndarray:
    """Paint one base-plus-overlays composite for a single patch.

    Parameters
    ----------
    images : dict of str to numpy.ndarray
        Original RGB patch arrays, keyed by marker key, for every marker
        referenced by ``combo``.
    masks : dict of str to numpy.ndarray
        Boolean detection masks (from :func:`_marker_mask`), keyed by
        marker key, for every marker referenced by ``combo``.
    combo : OverlayCombo
        Defines which marker is the base and which are layered on top,
        in order.
    cfg : IHCOverlayConfig
        Supplies ``base_render_mode`` and each marker's colour (via
        ``cfg.markers``).

    Returns
    -------
    numpy.ndarray
        ``(H, W, 3)`` ``uint8`` RGB composite image.

    Notes
    -----
    The base layer is either the base marker's own detection mask
    painted in its assigned colour on a black canvas
    (``base_render_mode="mask"``), or the base marker's original patch
    pixels used as-is (``base_render_mode="original"``). Each overlay
    marker is then painted on top, in list order, at full opacity —
    later overlays overwrite earlier ones (and the base) wherever their
    masks overlap, so combination order in
    ``OverlayCombo.overlays`` matters when markers spatially coincide.
    """
    base_profile = cfg.markers[combo.base]
    if cfg.base_render_mode == "original":
        canvas = images[combo.base].copy()
    else:  # "mask"
        canvas = np.zeros_like(images[combo.base])
        canvas[masks[combo.base]] = base_profile.color

    for marker_key in combo.overlays:
        profile = cfg.markers[marker_key]
        canvas[masks[marker_key]] = profile.color

    return canvas
