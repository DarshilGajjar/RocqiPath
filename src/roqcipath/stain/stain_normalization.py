"""
roqcipath.stain.stain_normalization
===================================
H&E stain normalisation — train or apply Reinhard / Macenko / Vahadane
normalisers over a folder of image patches.

This module wraps ``tiatoolbox.tools.stainnorm`` and adds:
  - target-statistic fitting from many patches (not just one target image)
  - persistence of fitted weights to a ``.npz`` file
  - a batch "train" / "apply" workflow with tissue-fraction filtering,
    resume support, and Rich-formatted progress/summary output

Quickstart
----------
Train a normaliser and save its weights::

    from roqcipath.stain.stain_normalization import (
        StainNormalizationConfig, run_stain_normalization_train,
    )

    run_stain_normalization_train(
        input_dir  = "./data/patches",
        output_dir = "./results/normalization",
        cfg        = StainNormalizationConfig(n_type="macenko"),
    )

Apply saved weights to a second folder of patches::

    from roqcipath.stain.stain_normalization import (
        StainNormalizationConfig, run_stain_normalization_apply,
    )

    run_stain_normalization_apply(
        input_dir  = "./data/patches_batch2",
        output_dir = "./results/normalization",
        cfg        = StainNormalizationConfig(n_type="macenko"),
    )

Single-image use, without the batch workflow::

    from roqcipath.stain.stain_normalization import get_normalizer

    norm = get_normalizer("macenko")
    norm.fit(target_rgb_image)
    normalized = norm.transform(source_rgb_image)

CLI
---
    python -m roqcipath.stain.stain_normalization --mode train -i ./patches -o ./results --n_type macenko
    python -m roqcipath.stain.stain_normalization --mode apply -i ./patches -o ./results --n_type macenko
"""

from __future__ import annotations

__all__ = [
    "StainNormalizationConfig",
    "ReinhardNormalizer",
    "MacenkoNormalizer",
    "VahadaneNormalizer",
    "get_normalizer",
    "run_stain_normalization_train",
    "run_stain_normalization_apply",
]

import sys
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cv2 as cv
import numpy as np

from roqcipath.exceptions import (
    ConfigurationError,
    DependencyError,
    ExtractionError,
)
from roqcipath.output import OutputLayout

# ---------------------------------------------------------------------------
# Logging — reuse the shared roqcipath logger; fall back gracefully
# ---------------------------------------------------------------------------

try:
    from roqcipath.logger import (
        logger,
        print_banner,
        print_section,
        print_step,
        print_done,
        print_warn,
        print_error,
        print_info,
        print_counts,
        print_summary_table,
        track,
    )
except Exception:  # pragma: no cover - logger should always be importable
    import logging as _sl

    logger = _sl.getLogger("roqcipath.stain.stain_normalization")  # type: ignore[assignment]

    def print_banner(*a: Any, **k: Any) -> None:
        """No-op fallback for ``roqcipath.logger.print_banner``.

        Accepts and ignores any arguments so call sites in this module
        don't need to special-case the fallback path. Used only when
        :mod:`roqcipath.logger` itself fails to import (unexpected, but
        guarded against defensively) — in that degraded scenario, the
        module falls back to the standard library's :mod:`logging`
        instead of Rich-based output, and skips the banner entirely.
        """
        ...
    def print_section(title: str) -> None:
        """Fallback for ``roqcipath.logger.print_section`` — logs ``title`` at INFO."""
        logger.info(title)
    def print_step(label: str, msg: str = "") -> None:
        """Fallback for ``roqcipath.logger.print_step`` — logs ``[label] msg`` at INFO."""
        logger.info(f"[{label}] {msg}")
    def print_done(msg: str) -> None:
        """Fallback for ``roqcipath.logger.print_done`` — logs ``msg`` at INFO, prefixed ``DONE:``."""
        logger.info(f"DONE: {msg}")
    def print_warn(msg: str) -> None:
        """Fallback for ``roqcipath.logger.print_warn`` — logs ``msg`` at WARNING."""
        logger.warning(msg)
    def print_error(msg: str) -> None:
        """Fallback for ``roqcipath.logger.print_error`` — logs ``msg`` at ERROR."""
        logger.error(msg)
    def print_info(msg: str) -> None:
        """Fallback for ``roqcipath.logger.print_info`` — logs ``msg`` at INFO."""
        logger.info(msg)
    def print_counts(ok: int, fail: int, label: str = "") -> None:
        """Fallback for ``roqcipath.logger.print_counts``.

        Parameters
        ----------
        ok : int
            Count of successful items.
        fail : int
            Count of failed items.
        label : str, optional
            Prefix describing what was counted.

        Notes
        -----
        Logs a single INFO line of the form ``"{label} ok={ok} fail={fail}"``
        in place of the Rich-formatted summary the real
        :func:`roqcipath.logger.print_counts` produces.
        """
        logger.info(f"{label} ok={ok} fail={fail}")
    def print_summary_table(rows: list, title: str = "") -> None:
        """Fallback for ``roqcipath.logger.print_summary_table``.

        Parameters
        ----------
        rows : list of tuple
            ``(key, value)`` pairs to display.
        title : str, optional
            Heading logged before the rows.

        Notes
        -----
        Logs ``title`` followed by one INFO line per ``(key, value)``
        pair, in place of the Rich-rendered table the real
        :func:`roqcipath.logger.print_summary_table` produces.
        """
        logger.info(title)
        for k, v in rows:
            logger.info(f"  {k}: {v}")
    def track(iterable: Any, description: str = "") -> Any:
        """Fallback for ``roqcipath.logger.track`` — returns ``iterable`` unmodified.

        Parameters
        ----------
        iterable : Any
            The iterable that would normally be wrapped with a Rich
            progress bar.
        description : str, optional
            Ignored; accepted only to match the real ``track``'s
            signature.

        Returns
        -------
        Any
            ``iterable``, unchanged — iterating it proceeds with no
            progress display in this degraded fallback path.
        """
        return iterable

# ---------------------------------------------------------------------------
# TIAToolbox — guarded import. Imported under private aliases so our own
# ReinhardNormalizer / MacenkoNormalizer / VahadaneNormalizer classes below
# never shadow (or get shadowed by) the upstream ones. This was the root
# cause of the bug in the original script: it imported tiatoolbox's classes
# by their public names and then redefined classes with those SAME names,
# so every internal `_TIAReinhardNormalizer()` / `_TIAMacenkoNormalizer()` /
# `_TIAVahadaneNormalizer()` reference resolved to nothing.
# ---------------------------------------------------------------------------

try:
    from tiatoolbox.tools.stainnorm import (
        ReinhardNormalizer as _TIAReinhardNormalizer,
        MacenkoNormalizer as _TIAMacenkoNormalizer,
        VahadaneNormalizer as _TIAVahadaneNormalizer,
    )
    _TIATOOLBOX_AVAILABLE = True
except ImportError:
    _TIATOOLBOX_AVAILABLE = False

    class _TIAReinhardNormalizer:  # type: ignore[no-redef]
        """Fallback stand-in for tiatoolbox's ``ReinhardNormalizer`` when
        ``tiatoolbox`` is not installed.

        Its sole purpose is to raise a clear, actionable error at the
        point of instantiation (rather than an opaque ``ImportError``
        somewhere deep in a normalizer's ``__init__``) — see
        :meth:`__init__`. It intentionally does not implement any of the
        real normalizer's methods (``fit``, ``transform``, etc.), since
        it is never meant to be used beyond raising.
        """

        def __init__(self) -> None:
            """Raise immediately, since tiatoolbox is not installed.

            Raises
            ------
            DependencyError
                Always. Carries the message
                ``"pip install tiatoolbox"`` so the resulting traceback
                tells the user exactly how to fix the problem.
            """
            raise DependencyError("tiatoolbox", "pip install tiatoolbox")

    _TIAMacenkoNormalizer = _TIAReinhardNormalizer  # type: ignore[assignment]
    _TIAVahadaneNormalizer = _TIAReinhardNormalizer  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMG_EXTS: frozenset = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"})


# ---------------------------------------------------------------------------
# I/O utilities
# ---------------------------------------------------------------------------

def imread_rgb(path: Path) -> Optional[np.ndarray]:
    """Read an image from *path* and return an RGB ``uint8`` array, or *None*."""
    bgr = cv.imread(str(path))
    if bgr is None:
        return None
    return cv.cvtColor(bgr, cv.COLOR_BGR2RGB)


def imwrite_rgb(path: Path, rgb: np.ndarray) -> None:
    """Write an RGB ``uint8`` array to *path*, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cv.imwrite(str(path), cv.cvtColor(rgb, cv.COLOR_RGB2BGR))


def discover_files(root: Union[str, Path], stains: List[str]) -> List[Path]:
    """Recursively find image files whose path contains at least one stain token.

    If *stains* is empty or contains ``"all"``, every image file under
    *root* is returned without filtering.
    """
    root = Path(root)
    if not stains or "all" in stains:
        return sorted(p for p in root.rglob("*") if p.suffix.lower() in IMG_EXTS)
    return sorted(
        p
        for p in root.rglob("*")
        if p.suffix.lower() in IMG_EXTS and any(s in p.parts for s in stains)
    )


def tissue_fraction(rgb: np.ndarray, thresh: float = 0.15) -> float:
    """Estimate the fraction of tissue pixels using optical-density thresholding."""
    od = -np.log((rgb.astype(np.float32) + 1.0) / 255.0 + 1e-6)
    return float((od.sum(axis=-1) > thresh).mean())


# ---------------------------------------------------------------------------
# Shared image-space utilities
# ---------------------------------------------------------------------------

def standardize_brightness(image: np.ndarray) -> np.ndarray:
    """Scale image intensity so the 90th percentile maps to 255."""
    p = np.percentile(image, 90)
    if p <= 0:
        return image.astype(np.uint8)
    return np.clip(image * 255.0 / p, 0, 255).astype(np.uint8)


def od_to_rgb(optical_density: np.ndarray) -> np.ndarray:
    """Convert optical density back to an RGB ``uint8`` image."""
    return (255 * np.exp(-optical_density)).astype(np.uint8)


# ---------------------------------------------------------------------------
# Format-conversion helpers for TIAToolbox's Reinhard attribute shapes
# (TIAToolbox stores target_means / target_stds as a tuple of (1, 1) arrays)
# ---------------------------------------------------------------------------

def _tia_means_to_flat(tia_means: tuple) -> np.ndarray:
    """Convert TIA's tuple-of-(1,1)-arrays to a flat (3,) float64 array."""
    return np.array([float(np.asarray(m).ravel()[0]) for m in tia_means], dtype=np.float64)


def _flat_to_tia_means(flat: np.ndarray) -> tuple:
    """Convert a flat (3,) array back to TIA's tuple-of-(1,1)-arrays."""
    return tuple(np.array([[v]], dtype=np.float64) for v in flat)


# ---------------------------------------------------------------------------
# Normaliser wrapper classes
# ---------------------------------------------------------------------------

class ReinhardNormalizer:
    """Colour normalisation via Reinhard *et al.* LAB statistics matching.

    Wraps :class:`tiatoolbox.tools.stainnorm.ReinhardNormalizer` and adds
    ``fit_from_patches`` (aggregate statistics over many patches instead
    of a single target image) plus ``save_weights`` / ``load_weights``.

    References
    ----------
    Reinhard *et al.*, "Color Transfer between Images", IEEE CGA 2001.
    """

    def __init__(self) -> None:
        """Construct an unfitted normaliser.

        Raises
        ------
        DependencyError
            If ``tiatoolbox`` is not installed. Call :meth:`fit` or
            :meth:`fit_from_patches` (or :meth:`load_weights`) before
            calling :meth:`transform`; ``target_means``/``target_stds``
            start as ``None`` and :meth:`transform` raises
            :class:`~roqcipath.exceptions.ExtractionError` if called too
            early.
        """
        if not _TIATOOLBOX_AVAILABLE:
            raise DependencyError("tiatoolbox", "pip install tiatoolbox")
        self._norm = _TIAReinhardNormalizer()
        self.target_means: Optional[np.ndarray] = None
        self.target_stds: Optional[np.ndarray] = None

    def fit(self, target: np.ndarray) -> "ReinhardNormalizer":
        """Compute target LAB statistics from a single *target* image."""
        logger.info("Reinhard | fitting target statistics (TIAToolbox) …")
        self._norm.fit(standardize_brightness(target))
        self.target_means = _tia_means_to_flat(self._norm.target_means)
        self.target_stds = _tia_means_to_flat(self._norm.target_stds)
        return self

    def fit_from_patches(self, patches: List[np.ndarray]) -> "ReinhardNormalizer":
        """Compute target LAB statistics incrementally from a list of patches."""
        logger.info(f"Reinhard | aggregating LAB statistics over {len(patches)} patches …")
        n_ch = 3
        px_count = 0
        ch_sum = np.zeros(n_ch, dtype=np.float64)
        ch_sum_sq = np.zeros(n_ch, dtype=np.float64)

        for patch in track(patches, "Reinhard — accumulating LAB stats"):
            patch = standardize_brightness(patch)
            for c, ch in enumerate(self._norm.lab_split(patch)):
                flat = ch.ravel().astype(np.float64)
                ch_sum[c] += flat.sum()
                ch_sum_sq[c] += (flat * flat).sum()
            px_count += patch.shape[0] * patch.shape[1]

        means = ch_sum / px_count
        stds = np.sqrt(np.maximum(ch_sum_sq / px_count - means ** 2, 0.0))
        logger.debug(f"Reinhard | means={np.round(means, 4)}  stds={np.round(stds, 4)}")

        self.target_means = means
        self.target_stds = stds
        self._norm.target_means = _flat_to_tia_means(means)
        self._norm.target_stds = _flat_to_tia_means(stds)
        return self

    def transform(self, image: np.ndarray) -> np.ndarray:
        """Normalise *image* to the fitted target statistics."""
        if self.target_means is None:
            raise ExtractionError("ReinhardNormalizer.transform called before fit().")
        return self._norm.transform(standardize_brightness(image))

    def save_weights(self, path: Union[Path, str]) -> None:
        """Persist the fitted target LAB statistics to a ``.npz`` file.

        Parameters
        ----------
        path : Path or str
            Destination file path. Parent directories are created if
            they don't already exist.

        Notes
        -----
        Saves ``target_means`` and ``target_stds`` (each a flat
        ``(3,)`` array — one value per LAB channel) via
        :func:`numpy.savez`. Load them back later with
        :meth:`load_weights`, either on this same instance or a fresh
        one, to reuse a fitted target without re-running :meth:`fit` or
        :meth:`fit_from_patches`.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, means=self.target_means, stds=self.target_stds)
        logger.debug(f"Reinhard | weights saved → {path}")

    def load_weights(self, path: Union[Path, str]) -> "ReinhardNormalizer":
        """Load previously saved target LAB statistics from a ``.npz`` file.

        Parameters
        ----------
        path : Path or str
            Path to a file previously written by :meth:`save_weights`.

        Returns
        -------
        ReinhardNormalizer
            ``self``, with ``target_means``/``target_stds`` populated
            (and the underlying TIAToolbox normaliser's matching
            attributes updated too), enabling method chaining, e.g.
            ``ReinhardNormalizer().load_weights(path).transform(img)``.

        Raises
        ------
        ExtractionError
            If ``path`` does not exist.
        """
        path = Path(path)
        if not path.is_file():
            raise ExtractionError(f"Reinhard weights not found: {path}")
        data = np.load(path)
        self.target_means = data["means"]
        self.target_stds = data["stds"]
        self._norm.target_means = _flat_to_tia_means(self.target_means)
        self._norm.target_stds = _flat_to_tia_means(self.target_stds)
        logger.debug(f"Reinhard | weights loaded ← {path}")
        return self


class MacenkoNormalizer:
    """Stain normalisation via the Macenko SVD method.

    References
    ----------
    Macenko *et al.*, "A method for normalizing histology slides for
    quantitative analysis", ISBI 2009.
    """

    def __init__(self) -> None:
        """Construct an unfitted normaliser.

        Raises
        ------
        DependencyError
            If ``tiatoolbox`` is not installed. Call :meth:`fit` (or
            :meth:`load_weights`) before calling :meth:`transform` or
            :meth:`hematoxylin`; ``stain_matrix_target`` starts as
            ``None`` and :meth:`transform` raises
            :class:`~roqcipath.exceptions.ExtractionError` if called too
            early.
        """
        if not _TIATOOLBOX_AVAILABLE:
            raise DependencyError("tiatoolbox", "pip install tiatoolbox")
        self._norm = _TIAMacenkoNormalizer()
        self.stain_matrix_target: Optional[np.ndarray] = None
        self.target_concentrations: Optional[np.ndarray] = None

    def fit(self, target: np.ndarray) -> "MacenkoNormalizer":
        """Extract stain matrix and concentrations from *target* image."""
        logger.info("Macenko | fitting stain matrix (TIAToolbox) …")
        self._norm.fit(standardize_brightness(target))
        self.stain_matrix_target = self._norm.stain_matrix_target
        self.target_concentrations = self._norm.target_concentrations
        return self

    def transform(self, image: np.ndarray) -> np.ndarray:
        """Normalise *image* to the fitted target stain matrix."""
        if self.stain_matrix_target is None:
            raise ExtractionError("MacenkoNormalizer.transform called before fit().")
        return self._norm.transform(standardize_brightness(image))

    def hematoxylin(self, image: np.ndarray) -> np.ndarray:
        """Return the hematoxylin channel of *image* as a 2-D float array."""
        image = standardize_brightness(image)
        h, w, _ = image.shape
        sm_src = self._norm.extractor.get_stain_matrix(image)
        conc = self._norm.get_concentrations(image, sm_src)
        return np.exp(-conc[:, 0].reshape(h, w))

    def target_stains(self) -> np.ndarray:
        """Convert the target stain matrix back to RGB for visualisation."""
        return od_to_rgb(self.stain_matrix_target)

    def save_weights(self, path: Union[Path, str]) -> None:
        """Persist the fitted stain matrix and target concentrations to a ``.npz`` file.

        Parameters
        ----------
        path : Path or str
            Destination file path. Parent directories are created if
            they don't already exist.

        Notes
        -----
        Saves ``stain_matrix_target`` (as ``"sm"``) and
        ``target_concentrations`` (as ``"tc"``) via :func:`numpy.savez`.
        Load them back later with :meth:`load_weights` to reuse a fitted
        target without re-running :meth:`fit`.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, sm=self.stain_matrix_target, tc=self.target_concentrations)
        logger.debug(f"Macenko | weights saved → {path}")

    def load_weights(self, path: Union[Path, str]) -> "MacenkoNormalizer":
        """Load a previously saved stain matrix and target concentrations.

        Parameters
        ----------
        path : Path or str
            Path to a file previously written by :meth:`save_weights`.

        Returns
        -------
        MacenkoNormalizer
            ``self``, with ``stain_matrix_target``/``target_concentrations``
            populated (and the underlying TIAToolbox normaliser's
            matching attributes updated too), enabling method chaining.

        Raises
        ------
        ExtractionError
            If ``path`` does not exist.
        """
        path = Path(path)
        if not path.is_file():
            raise ExtractionError(f"Macenko weights not found: {path}")
        data = np.load(path)
        self.stain_matrix_target = data["sm"]
        self.target_concentrations = data["tc"]
        self._norm.stain_matrix_target = self.stain_matrix_target
        self._norm.target_concentrations = self.target_concentrations
        logger.debug(f"Macenko | weights loaded ← {path}")
        return self


class VahadaneNormalizer:
    """Stain normalisation via the Vahadane sparse dictionary method.

    References
    ----------
    Vahadane *et al.*, "Structure-Preserving Color Normalization and Sparse
    Stain Separation for Histological Images", IEEE TMI 2016.
    """

    def __init__(self) -> None:
        """Construct an unfitted normaliser.

        Raises
        ------
        DependencyError
            If ``tiatoolbox`` is not installed. Call :meth:`fit` (or
            :meth:`load_weights`) before calling :meth:`transform` or
            :meth:`hematoxylin`; ``stain_matrix_target`` starts as
            ``None`` and :meth:`transform` raises
            :class:`~roqcipath.exceptions.ExtractionError` if called too
            early.
        """
        if not _TIATOOLBOX_AVAILABLE:
            raise DependencyError("tiatoolbox", "pip install tiatoolbox")
        self._norm = _TIAVahadaneNormalizer()
        self.stain_matrix_target: Optional[np.ndarray] = None

    def fit(self, target: np.ndarray) -> "VahadaneNormalizer":
        """Learn the target stain matrix via TIAToolbox's Vahadane fitter."""
        logger.info("Vahadane | fitting stain dictionary (TIAToolbox) …")
        self._norm.fit(standardize_brightness(target))
        self.stain_matrix_target = self._norm.stain_matrix_target
        return self

    def transform(self, image: np.ndarray) -> np.ndarray:
        """Normalise *image* to the fitted target stain matrix."""
        if self.stain_matrix_target is None:
            raise ExtractionError("VahadaneNormalizer.transform called before fit().")
        return self._norm.transform(standardize_brightness(image))

    def hematoxylin(self, image: np.ndarray) -> np.ndarray:
        """Return the hematoxylin channel of *image* as a 2-D float array."""
        image = standardize_brightness(image)
        h, w, _ = image.shape
        sm_src = self._norm.extractor.get_stain_matrix(image)
        conc = self._norm.get_concentrations(image, sm_src)
        return np.exp(-conc[:, 0].reshape(h, w))

    def target_stains(self) -> np.ndarray:
        """Convert the target stain matrix back to RGB for visualisation."""
        return od_to_rgb(self.stain_matrix_target)

    def save_weights(self, path: Union[Path, str]) -> None:
        """Persist the fitted stain matrix to a ``.npz`` file.

        Parameters
        ----------
        path : Path or str
            Destination file path. Parent directories are created if
            they don't already exist.

        Notes
        -----
        Saves ``stain_matrix_target`` (as ``"sm"``) via
        :func:`numpy.savez`. Load it back later with
        :meth:`load_weights` to reuse a fitted target without
        re-running :meth:`fit` (which, for Vahadane's sparse dictionary
        learning, can be comparatively slow).
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, sm=self.stain_matrix_target)
        logger.debug(f"Vahadane | weights saved → {path}")

    def load_weights(self, path: Union[Path, str]) -> "VahadaneNormalizer":
        """Load a previously saved stain matrix.

        Parameters
        ----------
        path : Path or str
            Path to a file previously written by :meth:`save_weights`.

        Returns
        -------
        VahadaneNormalizer
            ``self``, with ``stain_matrix_target`` populated (and the
            underlying TIAToolbox normaliser's matching attribute
            updated too), enabling method chaining.

        Raises
        ------
        ExtractionError
            If ``path`` does not exist.
        """
        path = Path(path)
        if not path.is_file():
            raise ExtractionError(f"Vahadane weights not found: {path}")
        data = np.load(path)
        self.stain_matrix_target = data["sm"]
        self._norm.stain_matrix_target = self.stain_matrix_target
        logger.debug(f"Vahadane | weights loaded ← {path}")
        return self


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_NORMALISER_REGISTRY: Dict[str, type] = {
    "reinhard": ReinhardNormalizer,
    "macenko": MacenkoNormalizer,
    "vahadane": VahadaneNormalizer,
}


def get_normalizer(name: str) -> Union[ReinhardNormalizer, MacenkoNormalizer, VahadaneNormalizer]:
    """Instantiate and return a normaliser by name (case-insensitive)."""
    key = name.lower()
    if key not in _NORMALISER_REGISTRY:
        raise ConfigurationError(
            f"Unknown normalisation type '{name}'. Choose from: {sorted(_NORMALISER_REGISTRY)}"
        )
    return _NORMALISER_REGISTRY[key]()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class StainNormalizationConfig:
    """Configuration for the stain-normalisation train / apply workflows.

    Parameters
    ----------
    n_type : str
        Normalisation algorithm — one of ``"reinhard"``, ``"macenko"``,
        ``"vahadane"``.
    stains : list[str]
        Stain folder tokens used to filter input files (matched against
        path components). Use ``["all"]`` to disable filtering.
    fit_min_tissue : float
        Minimum tissue fraction (0-1) for a patch to be used during
        training.
    max_train_patches : int
        Maximum number of tissue patches used to build the training
        mosaic (Macenko / Vahadane only; has no effect for Reinhard,
        which aggregates statistics incrementally over all patches).
    resume : bool
        Skip patches whose output file already exists (apply mode only).
    weights_path : str or None
        Explicit path to the ``.npz`` weights file. Defaults to
        ``<output_dir>/<n_type>_weights.npz`` in both train and apply mode.

    Examples
    --------
    Default Macenko training config::

        StainNormalizationConfig(n_type="macenko")

    Reinhard, no stain-folder filtering, resume on apply::

        StainNormalizationConfig(n_type="reinhard", stains=["all"], resume=True)
    """
    n_type: str = "macenko"
    stains: List[str] = field(default_factory=lambda: ["he"])
    fit_min_tissue: float = 0.1
    max_train_patches: int = 1000
    resume: bool = False
    weights_path: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate and normalise fields immediately after construction.

        Runs automatically after dataclass construction (the standard
        ``__post_init__`` hook).

        Raises
        ------
        ConfigurationError
            If ``n_type`` (case-insensitive) is not one of the
            registered normaliser names in ``_NORMALISER_REGISTRY``
            (``"reinhard"``, ``"macenko"``, ``"vahadane"``), if
            ``fit_min_tissue`` is outside ``[0.0, 1.0]``, or if
            ``max_train_patches`` is less than 1.

        Notes
        -----
        Besides validation, this also normalises two fields in place:

        - ``n_type`` is lowercased, so downstream code can compare it
          case-insensitively without repeating ``.lower()`` everywhere.
        - ``stains``, if passed as a comma-separated string (e.g.
          ``"he, marker_A, marker_B"``) rather than a list, is split on
          commas, stripped of surrounding whitespace per item, and empty
          entries are dropped — converting it to a proper
          ``list[str]`` for the rest of the pipeline to consume
          uniformly.
        """
        if self.n_type.lower() not in _NORMALISER_REGISTRY:
            raise ConfigurationError(
                f"n_type must be one of {sorted(_NORMALISER_REGISTRY)}; got '{self.n_type}'"
            )
        self.n_type = self.n_type.lower()
        if not (0.0 <= self.fit_min_tissue <= 1.0):
            raise ConfigurationError(f"fit_min_tissue must be in [0, 1]; got {self.fit_min_tissue}")
        if self.max_train_patches < 1:
            raise ConfigurationError(f"max_train_patches must be >= 1; got {self.max_train_patches}")
        if isinstance(self.stains, str):
            self.stains = [s.strip() for s in self.stains.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Workflow: train
# ---------------------------------------------------------------------------

def run_stain_normalization_train(input_dir: str, output_dir: str,
                                   cfg: Optional[StainNormalizationConfig] = None,
                                   ) -> Path:
    """Fit a normaliser on tissue patches under *input_dir* and save its weights.

    Parameters
    ----------
    input_dir : str
    output_dir : str
        Weights are written to ``<output_dir>/<cfg.n_type>_weights.npz``
        unless ``cfg.weights_path`` is set.
    cfg : StainNormalizationConfig or None

    Returns
    -------
    pathlib.Path
        Path to the saved weights file.
    """
    if cfg is None:
        cfg = StainNormalizationConfig()

    files = discover_files(input_dir, cfg.stains)
    normalizer = get_normalizer(cfg.n_type)
    module_dir = OutputLayout(output_dir).module_dir("stain_normalization")
    weights = Path(cfg.weights_path) if cfg.weights_path else module_dir / f"{cfg.n_type}_weights.npz"
    is_reinhard = isinstance(normalizer, ReinhardNormalizer)

    print_banner()

    if not files:
        print_error(f"No patches found in '{input_dir}' for stains {cfg.stains}. Aborting.")
        raise ExtractionError(f"No patches found in '{input_dir}' for stains {cfg.stains}")

    print_section("Training")
    print_summary_table([
        ("Algorithm", cfg.n_type.upper()),
        ("Input dir", input_dir),
        ("Stains", ", ".join(cfg.stains)),
        ("Total files", len(files)),
        ("Strategy", "incremental stats" if is_reinhard else f"mosaic  (max {cfg.max_train_patches} patches)"),
        ("Min tissue", f"{cfg.fit_min_tissue:.0%}"),
        ("Weights out", str(weights)),
    ], title="Train Config")

    # ── Phase 1: collect tissue patches ────────────────────────────────────
    print_step("SCAN", f"Sampling tissue patches (min tissue ≥ {cfg.fit_min_tissue:.0%}) …")
    picked: List[np.ndarray] = []
    for fp in track(files, "Scanning patches"):
        img = imread_rgb(fp)
        if img is not None and tissue_fraction(img) >= cfg.fit_min_tissue:
            picked.append(cv.resize(img, (256, 256)))

    if not picked:
        print_error("No tissue patches passed the tissue-fraction threshold. Training aborted.")
        raise ExtractionError("No tissue patches passed the tissue-fraction threshold.")

    print_info(f"Collected {len(picked)} tissue patches from {len(files)} files.")

    # ── Phase 2: fit ────────────────────────────────────────────────────────
    print_step("FIT", f"Fitting {cfg.n_type.upper()} normaliser …")

    if is_reinhard:
        normalizer.fit_from_patches(picked)
    else:
        cap = cfg.max_train_patches
        if len(picked) > cap:
            rng = np.random.default_rng(seed=42)
            picked = [picked[i] for i in rng.choice(len(picked), cap, replace=False)]
            print_info(f"Subsampled to {cap} patches for mosaic construction.")

        side = int(np.ceil(np.sqrt(len(picked))))
        canvas = np.zeros((side * 256, side * 256, 3), dtype=np.uint8)
        for idx, patch in enumerate(picked):
            r, c = divmod(idx, side)
            canvas[r * 256:(r + 1) * 256, c * 256:(c + 1) * 256] = patch
        print_info(f"Mosaic built: {canvas.shape[1]}×{canvas.shape[0]} px.")

        normalizer.fit(canvas)
        del canvas

    # ── Phase 3: save ─────────────────────────────────────────────────────
    print_step("SAVE", f"Writing weights → {weights}")
    normalizer.save_weights(weights)
    print_done(f"Weights saved → {weights}")
    return weights


# ---------------------------------------------------------------------------
# Workflow: apply
# ---------------------------------------------------------------------------

def run_stain_normalization_apply(input_dir: str, output_dir: str,
                                   cfg: Optional[StainNormalizationConfig] = None,
                                   ) -> Dict[str, int]:
    """Apply pre-fitted normaliser weights to a folder of patches.

    Parameters
    ----------
    input_dir : str
    output_dir : str
        Normalised images are written under ``<output_dir>/normalized_images``,
        mirroring the relative path of each input file.
    cfg : StainNormalizationConfig or None

    Returns
    -------
    dict
        ``{"processed": int, "skipped": int, "failed": int, "total": int}``
    """
    if cfg is None:
        cfg = StainNormalizationConfig()

    files = discover_files(input_dir, cfg.stains)
    normalizer = get_normalizer(cfg.n_type)
    layout = OutputLayout(output_dir)
    out_root = layout.module_dir("stain_normalization")
    weights = Path(cfg.weights_path) if cfg.weights_path else out_root / f"{cfg.n_type}_weights.npz"

    print_banner()

    if not files:
        print_error(f"No patches found in '{input_dir}' for stains {cfg.stains}. Aborting.")
        raise ExtractionError(f"No patches found in '{input_dir}' for stains {cfg.stains}")

    if not weights.is_file():
        print_error(f"Weights file not found: {weights}. Run train mode first.")
        raise ExtractionError(f"Weights file not found: {weights}")

    print_section("Applying Normalisation")
    print_summary_table([
        ("Algorithm", cfg.n_type.upper()),
        ("Input dir", input_dir),
        ("Weights", str(weights)),
        ("Output dir", str(out_root)),
        ("Patches", len(files)),
        ("Resume", "yes" if cfg.resume else "no"),
    ], title="Apply Config")

    print_step("LOAD", f"Loading weights ← {weights}")
    normalizer.load_weights(weights)

    processed = skipped = failed = 0

    print_step("NORM", "Normalising patches …")
    for fp in track(files, "Normalising"):
        relative = fp.relative_to(input_dir)
        item_name = "__".join(relative.with_suffix("").parts)
        out_path = layout.item_dir("stain_normalization", item_name) / fp.name

        if cfg.resume and out_path.exists():
            skipped += 1
            continue

        try:
            img = imread_rgb(fp)
            if img is None:
                raise ValueError("imread returned None")
            imwrite_rgb(out_path, normalizer.transform(img))
            processed += 1
        except Exception as exc:
            failed += 1
            print_warn(f"Failed [{fp.name}]: {exc}")

    print_counts(ok=processed, fail=failed, label="Normalisation")
    print_summary_table([
        ("Total", len(files)),
        ("Processed", processed),
        ("Skipped", skipped),
        ("Failed", failed),
        ("Output", str(out_root)),
    ], title="Apply Results")
    print_done("Normalisation complete.")

    return {"processed": processed, "skipped": skipped, "failed": failed, "total": len(files)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the ``python -m ...stain_normalization`` CLI.

    Returns
    -------
    argparse.ArgumentParser
        A configured parser accepting ``--mode`` (``train``/``apply``,
        required), ``-i``/``--in_dir`` (required), ``-o``/``--out_dir``,
        ``-w``/``--weights``, ``-s``/``--stains``, ``--n_type``
        (required, one of the registered normaliser names), ``--fit_min_tissue``,
        ``--max_train_patches``, and ``--resume``. See each argument's
        ``help`` text (shown via ``--help``, thanks to
        ``formatter_class=argparse.ArgumentDefaultsHelpFormatter`` which
        also appends each default value automatically) for details.
    """
    parser = argparse.ArgumentParser(
        prog="stain_normalization",
        description="Batch H&E stain normalisation (Reinhard / Macenko / Vahadane).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--mode", required=True, choices=["train", "apply"],
        help="'train' fits and saves normaliser weights; 'apply' uses saved weights.")
    parser.add_argument("-i", "--in_dir", required=True, metavar="DIR",
        help="Root directory containing input image patches.")
    parser.add_argument("-o", "--out_dir", default="./results/normalization", metavar="DIR",
        help="Output directory (apply mode) or weight directory (train mode).")
    parser.add_argument("-w", "--weights", default=None, metavar="FILE",
        help="Path to the .npz weights file. Defaults to <out_dir>/<n_type>_weights.npz.")
    parser.add_argument("-s", "--stains", default="he", metavar="STAIN[,STAIN…]",
        help="Comma-separated stain folder tokens used to filter input files ('all' = no filter).")
    parser.add_argument("--n_type", required=True, choices=sorted(_NORMALISER_REGISTRY),
        help="Normalisation algorithm.")
    parser.add_argument("--fit_min_tissue", type=float, default=0.1, metavar="FRAC",
        help="Minimum tissue fraction (0-1) for a patch to be used during training.")
    parser.add_argument("--max_train_patches", type=int, default=1000, metavar="N",
        help="Max tissue patches used to build the training mosaic (Macenko / Vahadane only).")
    parser.add_argument("--resume", action="store_true",
        help="Skip patches whose output file already exists (apply mode only).")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``python -m roqcipath.stain.stain_normalization``.

    Parses command-line arguments, builds a :class:`StainNormalizationConfig`
    from them, and dispatches to :func:`run_stain_normalization_train` or
    :func:`run_stain_normalization_apply` depending on ``--mode``.

    Parameters
    ----------
    argv : list of str, optional
        Argument list to parse, in the same form as :data:`sys.argv[1:]`.
        When ``None`` (the default), :mod:`argparse` reads from
        :data:`sys.argv` directly — passing an explicit list is mainly
        useful for testing this entry point without spawning a
        subprocess.

    Returns
    -------
    int
        Process exit code: ``0`` on success, ``1`` if a
        :class:`~roqcipath.exceptions.ConfigurationError`,
        :class:`~roqcipath.exceptions.ExtractionError`, or
        :class:`~roqcipath.exceptions.DependencyError` was raised and
        caught (with the error message printed via ``print_error``), or
        ``130`` (the conventional SIGINT exit code) if the user
        interrupted the run with Ctrl-C.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = StainNormalizationConfig(
            n_type=args.n_type,
            stains=args.stains,
            fit_min_tissue=args.fit_min_tissue,
            max_train_patches=args.max_train_patches,
            resume=args.resume,
            weights_path=args.weights,
        )
        if args.mode == "train":
            run_stain_normalization_train(args.in_dir, args.out_dir, cfg)
        else:
            run_stain_normalization_apply(args.in_dir, args.out_dir, cfg)
        return 0
    except (ConfigurationError, ExtractionError, DependencyError) as exc:
        print_error(str(exc))
        return 1
    except KeyboardInterrupt:
        print_warn("Interrupted by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
