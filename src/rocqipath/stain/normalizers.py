"""Stain-normalization algorithms and their weight serialization formats."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np

from rocqipath.core.console import track
from rocqipath.core.exceptions import ConfigurationError, DependencyError, ExtractionError
from rocqipath.core.logging import logger
from rocqipath.core.tissue import tissue_fraction as _shared_tissue_fraction


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
        """Represent an unavailable TIAToolbox normalizer.

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
    _TIAVahadaneNormalizer = _TIAReinhardNormalizer


def tissue_fraction(rgb: np.ndarray, thresh: float = 0.15) -> float:
    """Estimate the fraction of tissue pixels using optical-density thresholding."""
    return _shared_tissue_fraction(
        rgb,
        method="optical_density_sum",
        optical_density_threshold=thresh,
    )


def standardize_brightness(image: np.ndarray) -> np.ndarray:
    """Scale image intensity so the 90th percentile maps to 255."""
    p = np.percentile(image, 90)
    if p <= 0:
        return image.astype(np.uint8)
    return np.clip(image * 255.0 / p, 0, 255).astype(np.uint8)


def od_to_rgb(optical_density: np.ndarray) -> np.ndarray:
    """Convert optical density back to an RGB ``uint8`` image."""
    return (255 * np.exp(-optical_density)).astype(np.uint8)


def _tia_means_to_flat(tia_means: tuple) -> np.ndarray:
    """Convert TIA's tuple-of-(1,1)-arrays to a flat (3,) float64 array."""
    return np.array([float(np.asarray(m).ravel()[0]) for m in tia_means], dtype=np.float64)


def _flat_to_tia_means(flat: np.ndarray) -> tuple:
    """Convert a flat (3,) array back to TIA's tuple-of-(1,1)-arrays."""
    return tuple(np.array([[v]], dtype=np.float64) for v in flat)


class StainNormalizerBase:
    """Share archive persistence while subclasses retain their exact array schemas."""

    @staticmethod
    def _save_archive(path: Union[Path, str], **arrays: Optional[np.ndarray]) -> Path:
        """Create the parent directory and write a NumPy archive."""
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        np.savez(resolved, **arrays)
        return resolved

    @staticmethod
    def _load_archive(path: Union[Path, str], missing_message: str):
        """Validate and open a NumPy archive without changing its keys."""
        resolved = Path(path)
        if not resolved.is_file():
            raise ExtractionError(missing_message.format(path=resolved))
        return resolved, np.load(resolved)


class ReinhardNormalizer(StainNormalizerBase):
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
            :class:`~rocqipath.core.exceptions.ExtractionError` if called too
            early.
        """
        if not _TIATOOLBOX_AVAILABLE:
            raise DependencyError("tiatoolbox", "pip install tiatoolbox")
        self._norm = _TIAReinhardNormalizer()
        self.target_means: Optional[np.ndarray] = None
        self.target_stds: Optional[np.ndarray] = None

    def fit(self, target: np.ndarray) -> "ReinhardNormalizer":
        """Fit target LAB statistics from one RGB image.

        Parameters
        ----------
        target : numpy.ndarray
            ``(height, width, 3)`` RGB ``uint8`` target image.

        Returns
        -------
        ReinhardNormalizer
            This fitted instance.
        """
        logger.info("Reinhard | fitting target statistics (TIAToolbox) …")
        self._norm.fit(standardize_brightness(target))
        self.target_means = _tia_means_to_flat(self._norm.target_means)
        self.target_stds = _tia_means_to_flat(self._norm.target_stds)
        return self

    def fit_from_patches(self, patches: List[np.ndarray]) -> "ReinhardNormalizer":
        """Fit aggregate LAB statistics from RGB patches.

        Parameters
        ----------
        patches : list of numpy.ndarray
            RGB ``uint8`` patches. All pixels contribute equally.

        Returns
        -------
        ReinhardNormalizer
            This fitted instance.

        Notes
        -----
        Channel sums and squared sums accumulate in ``float64`` to avoid
        building a potentially large mosaic.
        """
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
        stds = np.sqrt(np.maximum(ch_sum_sq / px_count - means**2, 0.0))
        logger.debug(f"Reinhard | means={np.round(means, 4)}  stds={np.round(stds, 4)}")

        self.target_means = means
        self.target_stds = stds
        self._norm.target_means = _flat_to_tia_means(means)
        self._norm.target_stds = _flat_to_tia_means(stds)
        return self

    def transform(self, image: np.ndarray) -> np.ndarray:
        """Normalize an RGB image to the fitted LAB statistics.

        Parameters
        ----------
        image : numpy.ndarray
            ``(height, width, 3)`` RGB image.

        Returns
        -------
        numpy.ndarray
            Normalized RGB image with the original spatial dimensions.

        Raises
        ------
        ExtractionError
            If neither fitting nor weight loading has populated the target.
        """
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
        path = self._save_archive(
            path,
            means=self.target_means,
            stds=self.target_stds,
        )
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
        path, data = self._load_archive(path, "Reinhard weights not found: {path}")
        self.target_means = data["means"]
        self.target_stds = data["stds"]
        self._norm.target_means = _flat_to_tia_means(self.target_means)
        self._norm.target_stds = _flat_to_tia_means(self.target_stds)
        logger.debug(f"Reinhard | weights loaded ← {path}")
        return self


class MacenkoNormalizer(StainNormalizerBase):
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
            :class:`~rocqipath.core.exceptions.ExtractionError` if called too
            early.
        """
        if not _TIATOOLBOX_AVAILABLE:
            raise DependencyError("tiatoolbox", "pip install tiatoolbox")
        self._norm = _TIAMacenkoNormalizer()
        self.stain_matrix_target: Optional[np.ndarray] = None
        self.target_concentrations: Optional[np.ndarray] = None

    def fit(self, target: np.ndarray) -> "MacenkoNormalizer":
        """Fit a stain matrix and concentrations from an RGB target.

        Parameters
        ----------
        target : numpy.ndarray
            ``(height, width, 3)`` RGB target image.

        Returns
        -------
        MacenkoNormalizer
            This fitted instance.
        """
        logger.info("Macenko | fitting stain matrix (TIAToolbox) …")
        self._norm.fit(standardize_brightness(target))
        self.stain_matrix_target = self._norm.stain_matrix_target
        self.target_concentrations = self._norm.target_concentrations
        return self

    def transform(self, image: np.ndarray) -> np.ndarray:
        """Normalize an RGB image to the fitted Macenko target.

        Parameters
        ----------
        image : numpy.ndarray
            ``(height, width, 3)`` RGB image.

        Returns
        -------
        numpy.ndarray
            Normalized RGB image.

        Raises
        ------
        ExtractionError
            If the target stain matrix is unavailable.
        """
        if self.stain_matrix_target is None:
            raise ExtractionError("MacenkoNormalizer.transform called before fit().")
        return self._norm.transform(standardize_brightness(image))

    def hematoxylin(self, image: np.ndarray) -> np.ndarray:
        """Separate the hematoxylin channel from an RGB image.

        Parameters
        ----------
        image : numpy.ndarray
            ``(height, width, 3)`` RGB image.

        Returns
        -------
        numpy.ndarray
            Two-dimensional floating-point hematoxylin intensity.
        """
        image = standardize_brightness(image)
        h, w, _ = image.shape
        sm_src = self._norm.extractor.get_stain_matrix(image)
        conc = self._norm.get_concentrations(image, sm_src)
        return np.exp(-conc[:, 0].reshape(h, w))

    def target_stains(self) -> np.ndarray:
        """Render the fitted target stain vectors as RGB values.

        Returns
        -------
        numpy.ndarray
            RGB representation of the target stain matrix.
        """
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
        path = self._save_archive(
            path,
            sm=self.stain_matrix_target,
            tc=self.target_concentrations,
        )
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
        path, data = self._load_archive(path, "Macenko weights not found: {path}")
        self.stain_matrix_target = data["sm"]
        self.target_concentrations = data["tc"]
        self._norm.stain_matrix_target = self.stain_matrix_target
        self._norm.target_concentrations = self.target_concentrations
        logger.debug(f"Macenko | weights loaded ← {path}")
        return self


class VahadaneNormalizer(StainNormalizerBase):
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
            :class:`~rocqipath.core.exceptions.ExtractionError` if called too
            early.
        """
        if not _TIATOOLBOX_AVAILABLE:
            raise DependencyError("tiatoolbox", "pip install tiatoolbox")
        self._norm = _TIAVahadaneNormalizer()
        self.stain_matrix_target: Optional[np.ndarray] = None

    def fit(self, target: np.ndarray) -> "VahadaneNormalizer":
        """Fit a Vahadane stain dictionary from an RGB target.

        Parameters
        ----------
        target : numpy.ndarray
            ``(height, width, 3)`` RGB target image.

        Returns
        -------
        VahadaneNormalizer
            This fitted instance.
        """
        logger.info("Vahadane | fitting stain dictionary (TIAToolbox) …")
        self._norm.fit(standardize_brightness(target))
        self.stain_matrix_target = self._norm.stain_matrix_target
        return self

    def transform(self, image: np.ndarray) -> np.ndarray:
        """Normalize an RGB image to the fitted Vahadane target.

        Parameters
        ----------
        image : numpy.ndarray
            ``(height, width, 3)`` RGB image.

        Returns
        -------
        numpy.ndarray
            Normalized RGB image.

        Raises
        ------
        ExtractionError
            If the target stain matrix is unavailable.
        """
        if self.stain_matrix_target is None:
            raise ExtractionError("VahadaneNormalizer.transform called before fit().")
        return self._norm.transform(standardize_brightness(image))

    def hematoxylin(self, image: np.ndarray) -> np.ndarray:
        """Separate the hematoxylin channel from an RGB image.

        Parameters
        ----------
        image : numpy.ndarray
            ``(height, width, 3)`` RGB image.

        Returns
        -------
        numpy.ndarray
            Two-dimensional floating-point hematoxylin intensity.
        """
        image = standardize_brightness(image)
        h, w, _ = image.shape
        sm_src = self._norm.extractor.get_stain_matrix(image)
        conc = self._norm.get_concentrations(image, sm_src)
        return np.exp(-conc[:, 0].reshape(h, w))

    def target_stains(self) -> np.ndarray:
        """Render the fitted target stain vectors as RGB values.

        Returns
        -------
        numpy.ndarray
            RGB representation of the target stain matrix.
        """
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
        path = self._save_archive(path, sm=self.stain_matrix_target)
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
        path, data = self._load_archive(path, "Vahadane weights not found: {path}")
        self.stain_matrix_target = data["sm"]
        self._norm.stain_matrix_target = self.stain_matrix_target
        logger.debug(f"Vahadane | weights loaded ← {path}")
        return self


_NORMALISER_REGISTRY: Dict[str, type] = {
    "reinhard": ReinhardNormalizer,
    "macenko": MacenkoNormalizer,
    "vahadane": VahadaneNormalizer,
}


def get_normalizer(name: str) -> Union[ReinhardNormalizer, MacenkoNormalizer, VahadaneNormalizer]:
    """Instantiate a stain normalizer by case-insensitive name.

    Parameters
    ----------
    name : {"reinhard", "macenko", "vahadane"}
        Normalization algorithm.

    Returns
    -------
    ReinhardNormalizer or MacenkoNormalizer or VahadaneNormalizer
        New, unfitted normalizer instance.

    Raises
    ------
    ConfigurationError
        If ``name`` is not registered.

    Examples
    --------
    >>> normalizer = get_normalizer("macenko")  # doctest: +SKIP
    """
    key = name.lower()
    if key not in _NORMALISER_REGISTRY:
        raise ConfigurationError(
            f"Unknown normalisation type '{name}'. Choose from: {sorted(_NORMALISER_REGISTRY)}"
        )
    return _NORMALISER_REGISTRY[key]()
