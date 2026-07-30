"""Focused regression coverage for helpers relocated into ``rocqipath.utils``."""

from __future__ import annotations

from pathlib import Path

import numpy as np

import rocqipath.utils as utils
from rocqipath.registration.registrar import WSIRegistrar
from rocqipath.utils.geometry import region_bbox, transform_coords
from rocqipath.utils.imageio import imread_rgb, imwrite_rgb
from rocqipath.utils.naming import extract_sample_id
from rocqipath.utils.vips import rgb_ome_xml


def test_original_utils_exports_are_exact() -> None:
    """Keep the former flat module's eight-name public surface unchanged."""
    assert set(utils.__all__) == {
        "detect_wsi_format",
        "discover_matching_files",
        "discover_patch_pairs",
        "find_aligned_wsi",
        "find_hne_ihc_pairs_by_suffix",
        "is_wsi_file",
        "list_wsi_files",
        "natural_sort_key",
    }


def test_sample_id_extraction_preserves_tma_keywords() -> None:
    """Preserve stain removal, underscore collapse, and custom-keyword handling."""
    assert extract_sample_id("Sample_0001_CD8.tif") == "Sample_0001"
    assert extract_sample_id("Block_A_CUSTOM.tiff", ("custom",)) == "Block_A"


def test_rgb_ome_xml_method_delegates_byte_identically() -> None:
    """Keep the registrar method's exact XML output after helper relocation."""
    expected = rgb_ome_xml(64, 32, "synthetic", 0.25, 0.5)
    actual = WSIRegistrar._rgb_ome_xml(64, 32, "synthetic", 0.25, 0.5)

    assert actual == expected
    assert 'SizeX="64"' in actual
    assert 'PhysicalSizeY="0.5"' in actual


def test_orb_coordinate_method_delegates_to_geometry_helper() -> None:
    """Preserve full-resolution scale conversion around an identity homography."""
    registrar = object.__new__(WSIRegistrar)
    registrar.method = "orb"
    registrar.orb_matrix = np.eye(3, dtype=np.float64)
    registrar.orb_ref_scale_x = 2.0
    registrar.orb_ref_scale_y = 4.0
    registrar.orb_tgt_scale_x = 3.0
    registrar.orb_tgt_scale_y = 5.0

    assert transform_coords(registrar, 20, 40) == (30, 50)
    assert registrar._transform_coords(20, 40) == (30, 50)


def test_region_bbox_nominal_geometry_is_unchanged() -> None:
    """Preserve named-region anchors when tissue search is not requested."""
    assert region_bbox(100, 80, 20, "center") == (40, 30, 60, 50)
    assert region_bbox(100, 80, 20, "top_left") == (5, 4, 25, 24)


def test_imageio_rgb_round_trip(tmp_path: Path) -> None:
    """Preserve RGB/BGR channel conversion in relocated OpenCV helpers."""
    rgb = np.array(
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [12, 34, 56]],
        ],
        dtype=np.uint8,
    )
    path = tmp_path / "rgb.png"

    imwrite_rgb(path, rgb)

    np.testing.assert_array_equal(imread_rgb(path), rgb)
