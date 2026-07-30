"""Characterize duplicate helpers before consolidating their implementations."""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
from PIL import Image

import rocqipath.extraction.engine as extraction_engine
import rocqipath.registration.alignment as alignment
import rocqipath.utils as public_utils
import rocqipath.visualization.comparison as wsi_compare
from rocqipath.analysis.cell_counting import PositiveCellCounter
from rocqipath.core.tissue import optical_density_otsu_mask
from rocqipath.extraction.patch_extraction import (
    ReversiblePatchExtractor,
    _find_aligned_target,
    _patch_is_tissue,
)
from rocqipath.stain.stain_normalization import tissue_fraction as stain_tissue_fraction


def _half_tissue_image() -> Image.Image:
    rgb = np.full((16, 16, 3), 255, dtype=np.uint8)
    rgb[:, :8] = (120, 80, 60)
    return Image.fromarray(rgb, mode="RGB")


def test_cell_count_tissue_gate_characterization() -> None:
    """Pin the analysis mask threshold, shape validation, and inclusive gate."""
    rgb = np.asarray(_half_tissue_image())
    counter = object.__new__(PositiveCellCounter)
    counter.tissue_threshold = 0.5

    mask = counter._tissue_mask(rgb)

    assert mask.dtype == np.bool_
    assert int(mask.sum()) == 128
    assert counter._is_tissue(rgb) is True
    counter.tissue_threshold = 0.5001
    assert counter._is_tissue(rgb) is False


def test_patch_tissue_gates_characterization() -> None:
    """Pin both PIL-based patch gates to grayscale<235 and an inclusive ratio."""
    image = _half_tissue_image()
    extractor = object.__new__(ReversiblePatchExtractor)
    extractor.tissue_threshold = 0.5

    assert extractor._is_tissue(image) is True
    assert _patch_is_tissue(image, 0.5) is True
    assert _patch_is_tissue(image, 0.5001) is False


def test_comparison_tissue_helpers_characterization() -> None:
    """Pin the WSI-comparison pixel and mean-score tissue semantics."""
    tissue = Image.new("RGB", (16, 16), (120, 80, 60))
    blank = Image.new("RGB", (16, 16), "white")
    bbox = (0, 0, 16, 16)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Image.Image.getdata is deprecated",
            category=DeprecationWarning,
        )
        assert wsi_compare._tissue_fraction(tissue, bbox) == 1.0
        assert wsi_compare._tissue_fraction(blank, bbox) == 0.0
    assert wsi_compare._is_tissue(220 / 255, 0.05) is True
    assert wsi_compare._is_tissue((220 / 255) + 1e-6, 0.05) is False
    assert wsi_compare._is_tissue(220 / 255, 0.0499) is False


def test_stain_tissue_fraction_characterization() -> None:
    """Pin optical-density tissue fraction and its strict threshold comparison."""
    rgb = np.full((4, 4, 3), 255, dtype=np.uint8)
    rgb[:2] = 0

    assert stain_tissue_fraction(rgb) == 0.5
    assert stain_tissue_fraction(np.full((2, 2, 3), 255, dtype=np.uint8)) == 0.0


def test_orb_optical_density_mask_characterization() -> None:
    """Pin the registration OD/Otsu/morphology mask byte-for-byte."""
    rgb = np.full((128, 128, 3), 255, dtype=np.uint8)
    rgb[32:96, 32:96] = (120, 80, 60)

    mask = optical_density_otsu_mask(rgb)

    assert mask.dtype == np.uint8
    assert mask.shape == (128, 128)
    assert np.count_nonzero(mask) == 3904
    assert set(np.unique(mask)) == {0, 255}


def test_wsi_discovery_variants_characterization(tmp_path: Path) -> None:
    """Pin natural/recursive utility behavior versus flat alignment behavior."""
    for name in ("slide10.svs", "slide2.svs", "sample.ome.tiff", "Z.ndpi", "ignore.txt"):
        (tmp_path / name).touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "slide1.svs").touch()

    assert public_utils.is_wsi_file("sample.OME.TIFF") is True
    assert alignment.is_wsi_file("sample.OME.TIFF") is True
    assert public_utils.list_wsi_files(str(tmp_path)) == [
        "sample.ome.tiff",
        "slide2.svs",
        "slide10.svs",
        "Z.ndpi",
    ]
    assert public_utils.list_wsi_files(str(tmp_path), recursive=True) == [
        "nested/slide1.svs",
        "sample.ome.tiff",
        "slide2.svs",
        "slide10.svs",
        "Z.ndpi",
    ]
    assert alignment.list_wsi_files(tmp_path) == [
        "sample.ome.tiff",
        "slide10.svs",
        "slide2.svs",
        "Z.ndpi",
    ]


def test_extraction_logging_characterization(tmp_path: Path, monkeypatch) -> None:
    """Pin extraction logging as additive and file-path based."""
    calls = []
    monkeypatch.setattr(
        extraction_engine,
        "add_log_file",
        lambda path, *, level: calls.append((path, level)),
    )

    extraction_engine.configure_logging()
    extraction_engine.configure_logging(
        str(tmp_path),
        file_level="INFO",
        log_filename="tissue.log",
    )

    assert calls == [(str((tmp_path / "tissue.log").resolve()), "INFO")]


def test_comparison_logging_characterization(tmp_path: Path, monkeypatch) -> None:
    """Pin comparison logging as reset-plus-console-and-file configuration."""

    class FakeLogger:
        def __init__(self) -> None:
            self.events = []

        def remove(self) -> None:
            self.events.append(("remove",))

        def add(self, sink, **kwargs) -> None:
            self.events.append(("add", sink, kwargs))

        def info(self, message) -> None:
            self.events.append(("info", message))

    fake = FakeLogger()
    monkeypatch.setattr(wsi_compare, "logger", fake)

    wsi_compare.configure_logging("WSI Compare", "Synthetic", str(tmp_path))

    assert fake.events[0] == ("remove",)
    assert fake.events[1][0] == "add"
    assert fake.events[1][2]["level"] == "INFO"
    assert fake.events[1][2]["colorize"] is True
    assert fake.events[2][0:2] == ("add", str(tmp_path / "execution_log.log"))
    assert fake.events[2][2]["level"] == "DEBUG"
    assert fake.events[2][2]["rotation"] == "10 MB"
    assert fake.events[2][2]["retention"] == 5
    assert fake.events[3][0] == "info"
    assert "WSI Compare" in fake.events[3][1]
    assert "Synthetic" in fake.events[3][1]


def test_aligned_file_resolvers_characterization(tmp_path: Path) -> None:
    """Pin all three resolver paths and their biomarker-first tie breaking."""
    case_dir = tmp_path / "CD8" / "Sample_0001_he"
    case_dir.mkdir(parents=True)
    for name in ("a.ome.tiff", "x_cd8.ome.tiff", "z_aligned.ome.tiff"):
        (case_dir / name).touch()
    expected = str(case_dir / "x_cd8.ome.tiff")

    extractor = object.__new__(ReversiblePatchExtractor)
    extractor.aligned_root = str(tmp_path)

    assert public_utils.find_aligned_wsi(tmp_path, "CD8", "Sample_0001", "he") == expected
    assert extractor._find_aligned_ihc("Sample_0001", "CD8") == expected
    assert _find_aligned_target(str(tmp_path), "CD8", "Sample_0001", "he") == expected
