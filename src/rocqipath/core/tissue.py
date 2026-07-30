"""Shared tissue-mask primitives with explicit, behavior-preserving methods.

Heavy numerical and imaging dependencies are imported inside functions so this
domain primitive remains safe in a base-only RocqiPath installation.
"""

from __future__ import annotations

from typing import Any


def tissue_mask(
    rgb: Any,
    *,
    method: str = "mean_intensity",
    intensity_threshold: float = 235,
    optical_density_threshold: float = 0.15,
) -> Any:
    """Return a boolean tissue mask using a named historical method.

    Parameters
    ----------
    rgb : array-like
        Image with shape ``(height, width, channels)`` in 8-bit RGB
        intensity space. Coordinates are pixels in the supplied image,
        independent of slide pyramid level.
    method : {"mean_intensity", "optical_density_sum"}, optional
        Historical detector to apply.
    intensity_threshold : float, optional
        Pixels whose mean RGB intensity is strictly below this value are
        tissue for ``"mean_intensity"``.
    optical_density_threshold : float, optional
        Pixels whose summed optical density is strictly above this value
        are tissue for ``"optical_density_sum"``.

    Returns
    -------
    numpy.ndarray
        Boolean mask with shape ``(height, width)``.

    Raises
    ------
    ValueError
        If ``rgb`` has fewer than three channels for mean-intensity
        detection or if ``method`` is unknown.

    Notes
    -----
    The strict comparison directions and the ``+1``/``1e-6`` optical-density
    offsets preserve the formerly separate feature implementations.
    """
    import numpy as np

    if method == "mean_intensity":
        if rgb.ndim != 3 or rgb.shape[2] < 3:
            raise ValueError("rgb must have shape (height, width, channels>=3)")
        return np.mean(rgb[..., :3], axis=2) < intensity_threshold
    if method == "optical_density_sum":
        optical_density = -np.log((rgb.astype(np.float32) + 1.0) / 255.0 + 1e-6)
        return optical_density.sum(axis=-1) > optical_density_threshold
    raise ValueError(f"Unknown tissue-mask method: {method!r}")


def tissue_fraction(
    rgb: Any,
    *,
    method: str = "mean_intensity",
    intensity_threshold: float = 235,
    optical_density_threshold: float = 0.15,
) -> float:
    """Return the fraction of pixels selected by :func:`tissue_mask`.

    Parameters
    ----------
    rgb : array-like
        RGB pixels in the coordinate space being evaluated.
    method : {"mean_intensity", "optical_density_sum"}, optional
        Tissue detector passed unchanged to :func:`tissue_mask`.
    intensity_threshold : float, optional
        Mean-intensity cutoff on the 0–255 scale.
    optical_density_threshold : float, optional
        Summed optical-density cutoff.

    Returns
    -------
    float
        Tissue-pixel fraction in ``[0, 1]``.

    See Also
    --------
    is_tissue
        Apply an inclusive minimum-fraction gate.
    """
    import numpy as np

    mask = tissue_mask(
        rgb,
        method=method,
        intensity_threshold=intensity_threshold,
        optical_density_threshold=optical_density_threshold,
    )
    return float(np.mean(mask))


def is_tissue(
    rgb: Any,
    *,
    threshold: float,
    method: str = "mean_intensity",
    intensity_threshold: float = 235,
    optical_density_threshold: float = 0.15,
) -> bool:
    """Test whether a tissue fraction meets an inclusive cutoff.

    Parameters
    ----------
    rgb : array-like
        RGB pixels in the coordinate space being evaluated.
    threshold : float
        Minimum accepted tissue fraction in ``[0, 1]``.
    method : {"mean_intensity", "optical_density_sum"}, optional
        Tissue detector passed to :func:`tissue_fraction`.
    intensity_threshold : float, optional
        Mean-intensity cutoff on the 0–255 scale.
    optical_density_threshold : float, optional
        Summed optical-density cutoff.

    Returns
    -------
    bool
        ``True`` when the measured fraction is greater than or equal to
        ``threshold``.

    Notes
    -----
    The fraction comparison is inclusive even though each pixel-level
    intensity or optical-density comparison is strict.
    """
    return (
        tissue_fraction(
            rgb,
            method=method,
            intensity_threshold=intensity_threshold,
            optical_density_threshold=optical_density_threshold,
        )
        >= threshold
    )


def pil_intensity_fraction(image: Any, *, intensity_threshold: int = 235) -> float:
    """Return the historical grayscale tissue fraction for a PIL patch.

    Parameters
    ----------
    image : PIL.Image.Image
        Patch at any magnification or PIL mode; converted to grayscale.
    intensity_threshold : int, optional
        Strict grayscale cutoff on the 0–255 scale.

    Returns
    -------
    float
        Fraction of grayscale pixels strictly below the cutoff.
    """
    import numpy as np

    return float(np.mean(np.array(image.convert("L")) < intensity_threshold))


def pil_is_tissue(
    image: Any,
    *,
    threshold: float,
    intensity_threshold: int = 235,
) -> bool:
    """Test a PIL patch against an inclusive tissue-fraction cutoff.

    Parameters
    ----------
    image : PIL.Image.Image
        Patch at any magnification or PIL mode.
    threshold : float
        Minimum accepted tissue fraction in ``[0, 1]``.
    intensity_threshold : int, optional
        Strict grayscale tissue cutoff on the 0–255 scale.

    Returns
    -------
    bool
        Whether the patch fraction is greater than or equal to
        ``threshold``.
    """
    return pil_intensity_fraction(image, intensity_threshold=intensity_threshold) >= threshold


def pil_brightness_saturation_fraction(
    image: Any,
    bbox: tuple[int, int, int, int],
    *,
    thumbnail_size: int = 64,
    brightness_threshold: int = 220,
    saturation_threshold: float = 0.05,
) -> float:
    """Return brightness-and-saturation tissue coverage for a crop.

    Parameters
    ----------
    image : PIL.Image.Image
        Source image in any PIL mode.
    bbox : tuple of int
        ``(left, top, right, bottom)`` in source-image pixels.
    thumbnail_size : int, optional
        Width and height in pixels of the scoring thumbnail.
    brightness_threshold : int, optional
        Strict grayscale cutoff on the 0–255 scale.
    saturation_threshold : float, optional
        Strict HSV saturation cutoff expressed as a fraction in ``[0, 1]``.

    Returns
    -------
    float
        Fraction of thumbnail pixels passing both strict gates.

    Notes
    -----
    Resizing uses Pillow bilinear resampling. Changing the interpolation
    changes boundary pixels and therefore tissue coverage.
    """
    from PIL import Image

    crop = image.crop(bbox)
    thumbnail = crop.resize(
        (thumbnail_size, thumbnail_size),
        Image.Resampling.BILINEAR,
    )
    gray_values = list(thumbnail.convert("L").getdata())
    _hue, saturation, _value = thumbnail.convert("HSV").split()
    saturation_values = list(saturation.getdata())
    pixel_count = len(gray_values)
    tissue_count = sum(
        1
        for gray, sat in zip(gray_values, saturation_values)
        if gray < brightness_threshold and sat > (saturation_threshold * 255)
    )
    return tissue_count / pixel_count if pixel_count > 0 else 0.0


def brightness_saturation_is_tissue(
    brightness: float,
    saturation: float,
    *,
    brightness_threshold: int = 220,
    saturation_threshold: float = 0.05,
) -> bool:
    """Apply the historical mean brightness and saturation crop gate.

    Parameters
    ----------
    brightness : float
        Mean brightness normalized to ``[0, 1]``.
    saturation : float
        Mean saturation normalized to ``[0, 1]``.
    brightness_threshold : int, optional
        Inclusive brightness ceiling on the 0–255 scale.
    saturation_threshold : float, optional
        Inclusive saturation floor in ``[0, 1]``.

    Returns
    -------
    bool
        Whether both inclusive conditions pass.
    """
    return brightness <= brightness_threshold / 255.0 and saturation >= saturation_threshold


def optical_density_max_channel(rgb: Any) -> Any:
    """Convert RGB to the per-pixel maximum optical-density channel.

    Parameters
    ----------
    rgb : array-like
        ``(height, width, 3)`` RGB image on the 0–255 scale.

    Returns
    -------
    numpy.ndarray
        ``float32`` optical-density image with shape ``(height, width)``.

    Notes
    -----
    Intensities are clipped to ``[1, 255]`` before ``-log(rgb / 255)``;
    the lower bound avoids an infinite density at zero.
    """
    import numpy as np

    rgb_float = np.clip(rgb.astype(np.float32), 1.0, 255.0)
    optical_density = -np.log(rgb_float / 255.0)
    return np.max(optical_density, axis=2)


def optical_density_otsu_mask(
    rgb: Any,
    *,
    scale: float = 85.0,
    kernel_size: tuple[int, int] = (15, 15),
    close_iterations: int = 3,
    open_iterations: int = 2,
) -> Any:
    """Return the registration pathway's OD/Otsu morphology mask.

    Parameters
    ----------
    rgb : array-like
        ``(height, width, 3)`` RGB image, usually a registration
        thumbnail rather than level-0 slide pixels.
    scale : float, optional
        Multiplier converting optical density to the 8-bit Otsu input.
    kernel_size : tuple of int, optional
        Elliptical morphology kernel size in input-image pixels.
    close_iterations : int, optional
        Number of morphological closing iterations.
    open_iterations : int, optional
        Number of morphological opening iterations.

    Returns
    -------
    numpy.ndarray
        ``uint8`` mask with values 0 and 255.

    Notes
    -----
    Closing precedes opening. The default 15×15 kernel and iteration
    counts are scientifically observable registration behavior.
    """
    import cv2
    import numpy as np

    optical_density = optical_density_max_channel(rgb)
    optical_density_uint8 = np.uint8(np.clip(optical_density * scale, 0, 255))
    _threshold, mask = cv2.threshold(
        optical_density_uint8,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, kernel_size)
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=close_iterations,
    )
    return cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel,
        iterations=open_iterations,
    )


__all__ = [
    "brightness_saturation_is_tissue",
    "is_tissue",
    "optical_density_max_channel",
    "optical_density_otsu_mask",
    "pil_brightness_saturation_fraction",
    "pil_intensity_fraction",
    "pil_is_tissue",
    "tissue_fraction",
    "tissue_mask",
]
