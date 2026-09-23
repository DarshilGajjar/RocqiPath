"""Optional TIAToolbox tissue segmentation for extraction pipelines."""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _semantic_imports():
    """Load the optional semantic stack only when requested."""
    try:
        import openslide
        import torch
        import zarr
        from tiatoolbox.models import IOSegmentorConfig
        from tiatoolbox.models.engine.semantic_segmentor import SemanticSegmentor
    except (ImportError, OSError) as exc:
        raise ImportError(
            "Semantic tissue detection requires 'rocqipath[extraction,semantic]'."
        ) from exc
    return openslide, torch, zarr, IOSegmentorConfig, SemanticSegmentor


@lru_cache(maxsize=2)
def _segmentor(model: str, weights: str | None, device: str, batch_size: int, workers: int):
    """Create and reuse the expensive semantic model."""
    if weights is not None and not Path(weights).is_file():
        raise FileNotFoundError(f"Semantic model weights not found: {weights}")
    _openslide, torch, _zarr, _config, segmentor_type = _semantic_imports()
    resolved_device = "cuda" if device == "auto" and torch.cuda.is_available() else device
    if resolved_device == "auto":
        resolved_device = "cpu"
    if resolved_device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    return segmentor_type(
        model=model,
        weights=weights,
        device=resolved_device,
        batch_size=batch_size,
        num_workers=workers,
    )


def _prediction_array(group: Any):
    """Return the first likely prediction array from a Zarr hierarchy."""
    if hasattr(group, "shape") and not hasattr(group, "keys"):
        return group
    if not hasattr(group, "keys"):
        return None
    preferred = {"prediction", "predictions", "probabilities", "labels", "segmentation"}
    for key in group.keys():
        item = group[key]
        if hasattr(item, "shape") and key.lower() in preferred:
            return item
    for key in group.keys():
        item = group[key]
        if hasattr(item, "shape"):
            return item
        found = _prediction_array(item)
        if found is not None:
            return found
    return None


def _labels(prediction: np.ndarray) -> np.ndarray:
    """Convert class probabilities or labels to a two-dimensional label map."""
    prediction = np.squeeze(prediction)
    if prediction.ndim == 2:
        return prediction
    if prediction.ndim == 3 and 1 < prediction.shape[-1] <= 10:
        return np.argmax(prediction, axis=-1)
    if prediction.ndim == 3 and 1 < prediction.shape[0] <= 10:
        return np.argmax(prediction, axis=0)
    raise ValueError(f"Unexpected TIAToolbox prediction shape: {prediction.shape}")


def _native_mpp(path: Path, override: float | None) -> tuple[float, float]:
    """Read native slide MPP, using an explicit override when supplied."""
    if override is not None:
        return float(override), float(override)
    openslide, _torch, _zarr, _config, _segmentor_type = _semantic_imports()
    with openslide.OpenSlide(str(path)) as slide:
        x = slide.properties.get(openslide.PROPERTY_NAME_MPP_X)
        y = slide.properties.get(openslide.PROPERTY_NAME_MPP_Y)
    if x is None or y is None:
        raise RuntimeError(f"{path.name} has no MPP metadata; set semantic_source_mpp explicitly")
    mpp = float(x), float(y)
    if not all(np.isfinite(value) and value > 0 for value in mpp):
        raise RuntimeError(f"Invalid MPP metadata for {path.name}: {mpp}")
    return mpp


def semantic_mask(path: Path, cfg: Any) -> np.ndarray:
    """Run TIAToolbox and return a lightly cleaned boolean tissue mask."""
    _openslide, _torch, zarr, config_type, _segmentor_type = _semantic_imports()
    segmentor = _segmentor(
        cfg.semantic_model,
        cfg.semantic_weights_path,
        cfg.semantic_device,
        cfg.semantic_batch_size,
        cfg.semantic_num_workers,
    )
    ioconfig = config_type(
        input_resolutions=[{"units": "mpp", "resolution": 2.0}],
        output_resolutions=[{"units": "mpp", "resolution": 2.0}],
        patch_input_shape=(1024, 1024),
        patch_output_shape=(512, 512),
        stride_shape=(256, 256),
        save_resolution={"units": "mpp", "resolution": 8.0},
    )
    mpp = _native_mpp(path, cfg.semantic_source_mpp)
    with tempfile.TemporaryDirectory(prefix="rocqipath_semantic_") as directory:
        output_dir = Path(directory)
        result = segmentor.run(
            images=[path],
            ioconfig=ioconfig,
            patch_mode=False,
            auto_get_mask=False,
            wsireader_kwargs={"mpp": mpp},
            save_dir=output_dir,
            overwrite=True,
            output_type="zarr",
            return_probabilities=True,
        )
        candidates = sorted(output_dir.rglob("*.zarr"))
        if not candidates:
            values = list(result.values()) if isinstance(result, dict) else result
            if not isinstance(values, (list, tuple)):
                values = [values]
            candidates = [Path(value) for value in values if isinstance(value, (str, Path))]
        if not candidates:
            raise RuntimeError("Could not locate TIAToolbox Zarr prediction output")
        array = _prediction_array(zarr.open(str(candidates[0]), mode="r"))
        if array is None:
            raise RuntimeError("Could not locate a prediction array in TIAToolbox output")
        mask = _labels(np.asarray(array)) == 1

    binary = mask.astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    return binary.astype(bool)


def semantic_regions(path: Path, cfg: Any, *, strict_circles: bool = False):
    """Return normalized semantic boxes and rejected strict-circle candidates."""
    mask = semantic_mask(path, cfg)
    height, width = mask.shape
    contours, _hierarchy = cv2.findContours(
        mask.astype(np.uint8) * 255,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    min_area = height * width * cfg.min_area_fraction
    candidates = [contour for contour in contours if cv2.contourArea(contour) >= min_area]
    median_area = float(np.median([cv2.contourArea(c) for c in candidates])) if candidates else 0.0
    accepted: list[dict[str, float]] = []
    rejected: list[dict[str, Any]] = []

    for contour in candidates:
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        x, y, box_width, box_height = cv2.boundingRect(contour)
        hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
        metrics = {
            "circularity": float((4 * np.pi * area / perimeter**2) if perimeter else 0.0),
            "aspect_ratio": float(min(box_width, box_height) / max(box_width, box_height)),
            "solidity": float(area / hull_area if hull_area else 0.0),
            "relative_area": float(area / median_area if median_area else 0.0),
        }
        box = {
            "rx": x / width,
            "ry": y / height,
            "rw": box_width / width,
            "rh": box_height / height,
            **metrics,
        }
        reasons = []
        if strict_circles:
            limits = (
                ("circularity", cfg.min_circularity),
                ("aspect_ratio", cfg.min_aspect_ratio),
                ("solidity", cfg.min_solidity),
            )
            reasons.extend(name for name, limit in limits if metrics[name] < limit)
            if not cfg.min_relative_area <= metrics["relative_area"] <= cfg.max_relative_area:
                reasons.append("relative_area")
            if x == 0 or y == 0 or x + box_width == width or y + box_height == height:
                reasons.append("touches_border")
        if reasons:
            rejected.append({"box": box, "reasons": reasons})
        else:
            accepted.append(box)

    accepted.sort(key=lambda box: (box["ry"], box["rx"]))
    rejected.sort(key=lambda item: (item["box"]["ry"], item["box"]["rx"]))
    return accepted, rejected


__all__ = ["semantic_mask", "semantic_regions"]
