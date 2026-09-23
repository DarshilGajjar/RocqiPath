"""Focused coverage for optional semantic tissue-region geometry."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from rocqipath.extraction.config import ExtractTMAConfig, ExtractTissueConfig

from rocqipath.tissue import semantic


def test_otsu_remains_the_default_detector() -> None:
    """Preserve the existing extraction behavior unless explicitly changed."""
    assert ExtractTissueConfig().detector == "otsu"
    assert ExtractTMAConfig().detector == "otsu"


def test_semantic_config_rejects_invalid_runtime_values() -> None:
    """Fail configuration mistakes before model inference begins."""
    with pytest.raises(ValueError, match="semantic_batch_size must be >= 1"):
        ExtractTissueConfig(semantic_batch_size=0)
    with pytest.raises(ValueError, match="min_relative_area cannot exceed max_relative_area"):
        ExtractTMAConfig(min_relative_area=1.1, max_relative_area=0.9)


def test_semantic_tma_geometry_accepts_round_cores_and_records_rejections(
    monkeypatch,
) -> None:
    """Use semantic contours but retain only strict circular TMA candidates."""
    canvas = np.zeros((300, 500), dtype=np.uint8)
    for center in ((70, 80), (190, 80), (310, 80)):
        cv2.circle(canvas, center, 32, 1, thickness=cv2.FILLED)
    cv2.rectangle(canvas, (390, 45), (475, 90), 1, thickness=cv2.FILLED)
    cv2.circle(canvas, (20, 260), 30, 1, thickness=cv2.FILLED)
    mask = canvas.astype(bool)
    monkeypatch.setattr(semantic, "semantic_mask", lambda _path, _cfg: mask)

    cfg = ExtractTMAConfig(
        detector="semantic",
        min_area_fraction=0.001,
        min_circularity=0.80,
        min_aspect_ratio=0.90,
        min_solidity=0.95,
        min_relative_area=0.70,
        max_relative_area=1.30,
    )
    accepted, rejected = semantic.semantic_regions("slide.svs", cfg, strict_circles=True)

    assert len(accepted) == 3
    assert all(region["aspect_ratio"] >= 0.90 for region in accepted)
    assert len(rejected) == 2
    assert any("aspect_ratio" in item["reasons"] for item in rejected)
    assert any("touches_border" in item["reasons"] for item in rejected)


def test_semantic_wsi_keeps_irregular_tissue(monkeypatch) -> None:
    """Do not apply TMA shape gates to ordinary WSI tissue sections."""
    canvas = np.zeros((100, 150), dtype=np.uint8)
    points = np.array([[10, 10], [130, 20], [90, 45], [140, 80], [20, 90]])
    cv2.fillPoly(canvas, [points], 1)
    mask = canvas.astype(bool)
    monkeypatch.setattr(semantic, "semantic_mask", lambda _path, _cfg: mask)

    accepted, rejected = semantic.semantic_regions(
        "slide.svs",
        ExtractTissueConfig(detector="semantic", min_area_fraction=0.001),
    )

    assert len(accepted) == 1
    assert rejected == []
