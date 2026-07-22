"""
rocqipath.visualization.ihc_overlay
=====================================
Multi-marker IHC overlay compositing — detects each configured
biomarker's positive signal on a patch (via an HSV hue-range + saturation
gate followed by OTSU thresholding, the same detection family used by
:class:`rocqipath.analysis.cell_counting.PositiveCellCounter`, generalized
here to be per-marker configurable rather than fixed to a single "brown"
gate) and composites the results into coloured overlay figures — one
marker rendered as the base layer, with any number of additional markers
layered on top in their own assigned colours.

Works with any number of markers and any marker naming scheme — nothing
here is tied to a specific biomarker panel or a fixed two-marker layout.

Quickstart
----------
::

    from rocqipath.visualization.ihc_overlay import (
        IHCOverlayConfig, MarkerProfile, OverlayCombo, process_ihc_overlay,
    )

    cfg = IHCOverlayConfig(
        markers = {
            "CD31":   MarkerProfile(color=(0, 255, 0),   label="CD31"),
            "MARKER_B": MarkerProfile(color=(255, 0, 255), label="MARKER_B"),
        },
        combinations     = [OverlayCombo(base="CD31", overlays=["MARKER_B"])],
        base_marker      = "CD31",
        base_render_mode = "mask",
        plot_mode        = "composite",
        save_dir         = "./binary_plots",
    )

    results = process_ihc_overlay("./patches_dataset/case_001", cfg, mode="patch_dir")

Expected data structure
------------------------
::

    <case_dir>/
      <marker_key_1>/
        patch_0001.png
        patch_0002.png
      <marker_key_2>/
        patch_0001.png     # same filenames as marker_key_1 — patches are
        patch_0002.png     # matched across marker folders by filename

For a batch of cases, pass the parent directory instead — every immediate
subdirectory that itself looks like a case directory (i.e. contains at
least one recognised marker subfolder) is processed independently, and
:func:`process_ihc_overlay` returns one result dict per case.
"""

from __future__ import annotations

__all__ = [
    "MarkerProfile",
    "OverlayCombo",
    "IHCOverlayConfig",
    "process_ihc_overlay",
]

import concurrent.futures
import os
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

from rocqipath.exceptions import ConfigurationError, ExtractionError
from rocqipath.output import OutputLayout

#: Marker detection methods currently implemented. Only "hsv" exists today;
#: kept as an explicit set (rather than hardcoding the check inline) so a
#: future second method only needs adding here and to the actual detector
#: dispatch in :func:`_marker_mask`.
_SUPPORTED_METHODS = frozenset({"hsv"})

#: Valid values for :attr:`IHCOverlayConfig.base_render_mode`.
_BASE_RENDER_MODES = frozenset({"mask", "original"})

#: Valid values for :attr:`IHCOverlayConfig.plot_mode`.
_PLOT_MODES = frozenset({"grid", "composite", "both"})

#: Image file extensions considered when matching patch filenames across
#: marker subfolders.
_IMAGE_EXTENSIONS = (".png", ".tif", ".tiff", ".jpg", ".jpeg")


@dataclass
class MarkerProfile:
    """Detection and rendering settings for a single IHC marker/biomarker.

    Parameters
    ----------
    color : tuple of (int, int, int)
        RGB colour, each channel in ``[0, 255]``, used to paint this
        marker's detected pixels into any composite it participates in
        (as a base via ``base_render_mode="mask"``, or as an overlay).
    method : str, optional
        Detection method. Only ``"hsv"`` is currently implemented — an
        HSV hue-range + saturation gate (see ``hue_range``/``sat_min``
        below), refined by OTSU thresholding on the inverted Value
        channel within the gated region. Defaults to ``"hsv"``.
    label : str, optional
        Display name shown in grid-plot panel titles. When omitted
        (``None``), :meth:`IHCOverlayConfig.__post_init__` fills it in
        with the marker's dict key from ``IHCOverlayConfig.markers`` —
        so ``label`` only needs setting explicitly when you want the
        displayed name to differ from the dict key (e.g. dict key
        ``"pdgfeb"`` matching an on-disk folder name, displayed as
        ``"PDGFRB"``).
    hue_range : tuple of (int, int), optional
        Inclusive ``(low, high)`` hue bounds in OpenCV's HSV convention
        (``H`` in ``[0, 180]``), defining which hues count as this
        marker's signal. Defaults to ``(5, 20)`` — the same brown/DAB
        range used elsewhere in this package for chromogen detection.
        Widen or shift this per marker if your chromogen isn't brown.
    sat_min : int, optional
        Minimum saturation (``S`` in ``[0, 255]``) for a pixel to be
        considered inside the hue gate — excludes low-saturation
        near-white/near-grey background even if its hue happens to fall
        in range. Defaults to ``30``.
    value_threshold : int, optional
        Reserved for future non-HSV detection methods. Currently
        ignored — the ``"hsv"`` method always computes its own
        per-patch OTSU threshold rather than using a fixed value.

    Raises
    ------
    ConfigurationError
        Raised by :meth:`__post_init__` if ``method`` isn't a supported
        value, ``color`` isn't a valid 3-tuple of ``[0, 255]`` integers,
        ``hue_range`` isn't a valid ascending pair within ``[0, 180]``,
        or ``sat_min`` is outside ``[0, 255]``.
    """

    color: Tuple[int, int, int]
    method: str = "hsv"
    label: Optional[str] = None
    hue_range: Tuple[int, int] = (5, 20)
    sat_min: int = 30
    value_threshold: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate this marker's detection and rendering parameters.

        Raises
        ------
        ConfigurationError
            See the class docstring's Raises section for the exact
            conditions checked.
        """
        if self.method not in _SUPPORTED_METHODS:
            raise ConfigurationError(
                f"MarkerProfile.method must be one of {sorted(_SUPPORTED_METHODS)}; "
                f"got {self.method!r}"
            )
        if len(self.color) != 3 or not all(0 <= c <= 255 for c in self.color):
            raise ConfigurationError(
                f"color must be an (R, G, B) tuple with each value in [0, 255]; got {self.color}"
            )
        lo, hi = self.hue_range
        if not (0 <= lo <= hi <= 180):
            raise ConfigurationError(
                f"hue_range must satisfy 0 <= low <= high <= 180 (OpenCV hue "
                f"convention); got {self.hue_range}"
            )
        if not (0 <= self.sat_min <= 255):
            raise ConfigurationError(f"sat_min must be in [0, 255]; got {self.sat_min}")


@dataclass
class OverlayCombo:
    """One base-plus-overlays combination to render as a composite figure.

    A single :class:`IHCOverlayConfig` can define multiple combinations
    — e.g. one composite with every marker layered together, and another
    isolating just two of them — each produced as its own set of output
    files per patch.

    Parameters
    ----------
    base : str
        Marker key (matching a key in ``IHCOverlayConfig.markers``) to
        render as the bottom layer of the composite. See
        ``IHCOverlayConfig.base_render_mode`` for how the base layer is
        actually painted.
    overlays : list of str, optional
        Marker keys to layer on top of the base, in order — later
        entries are painted after (and therefore visually on top of)
        earlier ones wherever their detected regions overlap. Must be
        non-empty.

    Raises
    ------
    ConfigurationError
        Raised by :meth:`__post_init__` if ``overlays`` is empty. Note
        that whether ``base``/``overlays`` keys actually exist in a
        given config's ``markers`` dict is validated later, by
        :meth:`IHCOverlayConfig.__post_init__` — this class alone has no
        visibility into that registry.
    """

    base: str
    overlays: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate that at least one overlay marker was specified.

        Raises
        ------
        ConfigurationError
            If ``overlays`` is empty.
        """
        if not self.overlays:
            raise ConfigurationError(
                "OverlayCombo.overlays must be a non-empty list of marker keys."
            )


@dataclass
class IHCOverlayConfig:
    """Configuration for multi-marker IHC overlay compositing.

    Parameters
    ----------
    markers : dict of str to MarkerProfile
        Registry of every marker this config knows about, keyed by a
        short identifier matching the marker's on-disk subfolder name
        (case-insensitive at discovery time — see
        :func:`process_ihc_overlay`). Must be non-empty.
    combinations : list of OverlayCombo
        Which base/overlay combinations to render — see
        :class:`OverlayCombo`. Must be non-empty.
    base_marker : str
        Marker key used as the "primary" marker for informational
        purposes (e.g. deciding whether a directory looks like a case
        directory — see :func:`process_ihc_overlay`). Must exist in
        ``markers``. Distinct from each individual
        :attr:`OverlayCombo.base`, which is set per-combination and
        does not have to equal this field.
    base_render_mode : str, optional
        How each combination's base layer is painted:

        - ``"mask"`` (default) — paint the base marker's own colour,
          full opacity, wherever its detection mask is ``True``, on an
          otherwise black canvas.
        - ``"original"`` — use the base marker's original RGB patch
          pixels as the canvas, unmodified, with overlay markers then
          painted on top.
    plot_mode : str, optional
        Which output figure(s) to save per patch per combination:

        - ``"composite"`` (default) — the coloured composite only.
        - ``"grid"`` — one white-on-black binary-mask panel per marker
          in the combination, plus the coloured composite as a final
          panel, all in a single multi-panel figure.
        - ``"both"`` — save a grid file *and* a separate composite file.
    show_plot : bool, optional
        If ``True``, also display each figure interactively via
        :func:`matplotlib.pyplot.show` as it's generated (in addition to
        saving it). Defaults to ``False`` — appropriate for headless
        batch runs.
    save_dir : str, optional
        Root output directory. Created if it doesn't exist. Defaults to
        ``"./binary_plots"``. Each case's figures are written under
        ``save_dir/<case_id>/``.
    dpi : int, optional
        Resolution (dots per inch) for saved figures. Must be positive.
        Defaults to ``300``.
    patches_per_case : int, optional
        Maximum number of patches to process per case. ``0`` (the
        default) processes every patch found. A positive value samples
        that many patches at random (without replacement, via
        :func:`random.sample`) per case; if fewer patches exist than
        requested, all available patches are used instead.
    skip_existing : bool, optional
        If ``True`` (the default), a patch/combination whose expected
        output file(s) already exist on disk are skipped rather than
        regenerated — lets a batch run be safely resumed after an
        interruption.
    max_workers : int, optional
        Number of cases to process concurrently when
        :func:`process_ihc_overlay` is called in batch mode (multiple
        case directories under one parent). ``1`` (the default)
        processes cases sequentially; values greater than ``1`` use a
        :class:`concurrent.futures.ThreadPoolExecutor`. Has no effect
        when processing a single case directory.

    Raises
    ------
    ConfigurationError
        Raised by :meth:`__post_init__` — see that method for the full
        list of checks (non-empty ``markers``/``combinations``,
        ``base_marker`` and every combination's marker keys existing in
        ``markers``, valid ``base_render_mode``/``plot_mode``, positive
        ``dpi``, non-negative ``patches_per_case``, ``max_workers >= 1``).
    """

    markers: Dict[str, MarkerProfile]
    combinations: List[OverlayCombo]
    base_marker: str
    base_render_mode: str = "mask"
    plot_mode: str = "composite"
    show_plot: bool = False
    save_dir: str = "./binary_plots"
    dpi: int = 300
    patches_per_case: int = 0
    skip_existing: bool = True
    max_workers: int = 1

    def __post_init__(self) -> None:
        """Validate every field and cross-reference marker keys, then create ``save_dir``.

        Raises
        ------
        ConfigurationError
            If ``markers`` or ``combinations`` is empty; if
            ``base_marker``, or any :attr:`OverlayCombo.base` /
            ``overlays`` entry across all ``combinations``, references a
            key not present in ``markers``; if ``base_render_mode`` is
            not one of ``{"mask", "original"}``; if ``plot_mode`` is not
            one of ``{"grid", "composite", "both"}``; if ``dpi`` is not
            strictly positive; if ``patches_per_case`` is negative; or
            if ``max_workers`` is less than 1.

        Notes
        -----
        As a convenience, any :class:`MarkerProfile` in ``markers`` whose
        ``label`` is still ``None`` is backfilled here with its dict key,
        so callers don't have to repeat the key as the label when they
        already match (as in ``"CD31": MarkerProfile(..., label="CD31")``
        — that explicit repetition becomes optional). ``save_dir`` is
        created (including parents) if it doesn't already exist.
        """
        if not self.markers:
            raise ConfigurationError("markers must be a non-empty dict of MarkerProfile.")
        if self.base_marker not in self.markers:
            raise ConfigurationError(
                f"base_marker {self.base_marker!r} not found in markers: {sorted(self.markers)}"
            )
        if self.base_render_mode not in _BASE_RENDER_MODES:
            raise ConfigurationError(
                f"base_render_mode must be one of {sorted(_BASE_RENDER_MODES)}; "
                f"got {self.base_render_mode!r}"
            )
        if self.plot_mode not in _PLOT_MODES:
            raise ConfigurationError(
                f"plot_mode must be one of {sorted(_PLOT_MODES)}; got {self.plot_mode!r}"
            )
        if self.dpi <= 0:
            raise ConfigurationError(f"dpi must be > 0; got {self.dpi}")
        if self.patches_per_case < 0:
            raise ConfigurationError(f"patches_per_case must be >= 0; got {self.patches_per_case}")
        if self.max_workers < 1:
            raise ConfigurationError(f"max_workers must be >= 1; got {self.max_workers}")
        if not self.combinations:
            raise ConfigurationError("combinations must be a non-empty list of OverlayCombo.")
        for combo in self.combinations:
            if combo.base not in self.markers:
                raise ConfigurationError(
                    f"OverlayCombo.base {combo.base!r} not found in markers: {sorted(self.markers)}"
                )
            for ov in combo.overlays:
                if ov not in self.markers:
                    raise ConfigurationError(
                        f"OverlayCombo overlay {ov!r} not found in markers: {sorted(self.markers)}"
                    )

        for key, profile in self.markers.items():
            if not profile.label:
                profile.label = key

        os.makedirs(self.save_dir, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# Detection
# ══════════════════════════════════════════════════════════════════════════════


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


# ══════════════════════════════════════════════════════════════════════════════
# Compositing
# ══════════════════════════════════════════════════════════════════════════════


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


# ══════════════════════════════════════════════════════════════════════════════
# Discovery
# ══════════════════════════════════════════════════════════════════════════════


def _resolve_marker_dir(case_dir: str, marker_key: str) -> Optional[str]:
    """Find the subfolder of ``case_dir`` matching ``marker_key`` case-insensitively.

    Parameters
    ----------
    case_dir : str
        Directory expected to contain one subfolder per marker.
    marker_key : str
        Marker key to look for (matched case-insensitively against
        subfolder names, e.g. key ``"pdgfeb"`` matches an on-disk folder
        literally named ``"PDGFEB"``, ``"pdgfeb"``, or any other casing).

    Returns
    -------
    str or None
        Full path to the matched subfolder, or ``None`` if ``case_dir``
        doesn't exist or contains no subfolder matching ``marker_key``.
    """
    if not os.path.isdir(case_dir):
        return None
    for name in os.listdir(case_dir):
        full = os.path.join(case_dir, name)
        if name.lower() == marker_key.lower() and os.path.isdir(full):
            return full
    return None


def _looks_like_case_dir(path: str, marker_keys: List[str]) -> bool:
    """Decide whether ``path`` directly contains at least one recognised marker subfolder.

    Used by :func:`process_ihc_overlay` to distinguish a single case
    directory from a parent directory containing multiple cases.

    Parameters
    ----------
    path : str
        Directory to inspect.
    marker_keys : list of str
        Marker keys to check for (matched case-insensitively).

    Returns
    -------
    bool
        ``True`` if ``path`` exists and at least one of its immediate
        subdirectories matches one of ``marker_keys`` (case-insensitive);
        ``False`` otherwise.
    """
    if not os.path.isdir(path):
        return False
    existing = {n.lower() for n in os.listdir(path) if os.path.isdir(os.path.join(path, n))}
    return any(k.lower() in existing for k in marker_keys)


# ══════════════════════════════════════════════════════════════════════════════
# Per-case processing
# ══════════════════════════════════════════════════════════════════════════════


def _process_single_case(case_id: str, case_dir: str, cfg: IHCOverlayConfig) -> Dict[str, Any]:
    """Generate overlay figures for every patch in one case directory.

    Parameters
    ----------
    case_id : str
        Identifier for this case, used to name the output subdirectory
        (``cfg.save_dir/<case_id>/``).
    case_dir : str
        Directory containing one subfolder per marker (see the module
        docstring's "Expected data structure" section).
    cfg : IHCOverlayConfig
        Full configuration — markers, combinations, rendering and output
        options.

    Returns
    -------
    dict
        ``{"patches_processed": int, "figures_saved": int}``. Both are
        ``0`` if any required marker subfolder is missing, or if no
        patch filename is common to every required marker subfolder —
        in either case a warning is printed and the case is skipped
        rather than raising, since a partially organised dataset (a case
        missing one marker) is common.

    Notes
    -----
    Only the markers actually referenced by ``cfg.combinations`` (the
    union of every combination's ``base`` and ``overlays``) are
    resolved and loaded — markers present in ``cfg.markers`` but not
    used by any combination are ignored for this run. Patches are
    matched across marker subfolders by exact filename (not just stem —
    the extension must match too); only filenames present in *every*
    required marker's subfolder are processed. When
    ``cfg.patches_per_case > 0``, the matched filename list is randomly
    subsampled (via :func:`random.sample`) before processing.
    """
    needed_markers = sorted(
        {key for combo in cfg.combinations for key in [combo.base, *combo.overlays]}
    )

    marker_dirs: Dict[str, str] = {}
    for mk in needed_markers:
        d = _resolve_marker_dir(case_dir, mk)
        if d is None:
            print(f"[WARN] {case_id}: marker folder for '{mk}' not found — skipping case.")
            return {"patches_processed": 0, "figures_saved": 0}
        marker_dirs[mk] = d

    file_sets = [
        {f for f in os.listdir(d) if f.lower().endswith(_IMAGE_EXTENSIONS)}
        for d in marker_dirs.values()
    ]
    common = sorted(set.intersection(*file_sets)) if file_sets else []

    if not common:
        print(f"[WARN] {case_id}: no matching patch filenames across marker folders.")
        return {"patches_processed": 0, "figures_saved": 0}

    if cfg.patches_per_case and cfg.patches_per_case < len(common):
        common = sorted(random.sample(common, cfg.patches_per_case))

    case_save_dir = str(OutputLayout(cfg.save_dir).item_dir("visualization", case_id))

    patches_processed = 0
    figures_saved = 0

    for fname in common:
        stem = os.path.splitext(fname)[0]
        images = {
            mk: np.array(Image.open(os.path.join(marker_dirs[mk], fname)).convert("RGB"))
            for mk in needed_markers
        }
        masks = {mk: _marker_mask(images[mk], cfg.markers[mk]) for mk in needed_markers}
        patches_processed += 1

        for combo in cfg.combinations:
            combo_name = f"{combo.base}_" + "_".join(combo.overlays)
            out_composite = os.path.join(case_save_dir, f"{stem}_{combo_name}_composite.png")
            out_grid = os.path.join(case_save_dir, f"{stem}_{combo_name}_grid.png")

            need_composite = cfg.plot_mode in ("composite", "both")
            need_grid = cfg.plot_mode in ("grid", "both")

            if cfg.skip_existing:
                need_composite = need_composite and not os.path.exists(out_composite)
                need_grid = need_grid and not os.path.exists(out_grid)
                if not need_composite and not need_grid:
                    continue

            composite = _build_composite(images, masks, combo, cfg)

            if need_composite:
                _save_composite_figure(composite, out_composite, cfg)
                figures_saved += 1

            if need_grid:
                _save_grid_figure(images, masks, composite, combo, cfg, out_grid)
                figures_saved += 1

    return {"patches_processed": patches_processed, "figures_saved": figures_saved}


# ══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ══════════════════════════════════════════════════════════════════════════════


def process_ihc_overlay(
    data_in: str,
    cfg: IHCOverlayConfig,
    mode: str = "patch_dir",
) -> Union[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Generate multi-marker overlay figures for a single case or a batch of cases.

    Auto-detects which situation ``data_in`` represents: if it directly
    contains at least one recognised marker subfolder (see
    :func:`_looks_like_case_dir`), it's treated as a single case;
    otherwise, every immediate subdirectory of ``data_in`` that itself
    looks like a case directory is processed as a separate case.

    Parameters
    ----------
    data_in : str
        Either a single case directory, or a parent directory containing
        multiple case subdirectories.
    cfg : IHCOverlayConfig
        Full configuration — markers, combinations, rendering and output
        options.
    mode : str, optional
        Accepted for interface clarity/future extension but currently
        does not change behaviour — auto-detection (single case vs.
        batch) happens the same way regardless of this argument's value.
        Defaults to ``"patch_dir"``.

    Returns
    -------
    dict
        For a single case: ``{"patches_processed": int, "figures_saved": int}``.

        For a batch: ``{case_id: {"patches_processed": int, "figures_saved": int}, ...}``
        — one entry per processed case subdirectory, keyed by directory
        name.

    Raises
    ------
    ExtractionError
        If ``data_in`` is not itself a recognised single-case directory,
        and none of its immediate subdirectories look like case
        directories either — i.e. nothing processable was found at all.

    Notes
    -----
    **Parallelism.** In batch mode, when ``cfg.max_workers > 1`` and more
    than one case directory was found, cases are processed concurrently
    via a :class:`concurrent.futures.ThreadPoolExecutor` (same threads-
    over-processes rationale as
    :func:`rocqipath.extraction.patch_extraction.run_patch_extraction`:
    the work is I/O- and NumPy-bound, which releases the GIL, so threads
    capture most of the available concurrency without process-pool
    pickling overhead). With ``max_workers=1`` (the default) or only one
    case, processing is sequential.
    """
    marker_keys = list(cfg.markers.keys())

    if _looks_like_case_dir(data_in, marker_keys):
        case_id = os.path.basename(os.path.normpath(data_in))
        return _process_single_case(case_id, data_in, cfg)

    if not os.path.isdir(data_in):
        raise ExtractionError(f"data_in does not exist: {data_in}")

    case_dirs = [
        (d, os.path.join(data_in, d))
        for d in sorted(os.listdir(data_in))
        if _looks_like_case_dir(os.path.join(data_in, d), marker_keys)
    ]
    if not case_dirs:
        raise ExtractionError(
            f"No case directories with recognisable marker subfolders "
            f"({marker_keys}) found under: {data_in}"
        )

    results: Dict[str, Dict[str, Any]] = {}

    if cfg.max_workers > 1 and len(case_dirs) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
            futures = {
                pool.submit(_process_single_case, cid, cdir, cfg): cid for cid, cdir in case_dirs
            }
            for future in concurrent.futures.as_completed(futures):
                cid = futures[future]
                results[cid] = future.result()
    else:
        for cid, cdir in case_dirs:
            results[cid] = _process_single_case(cid, cdir, cfg)

    return results
