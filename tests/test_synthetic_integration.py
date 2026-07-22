"""Scanner-free integration tests for discovery, extraction, and manifests."""

from __future__ import annotations

import json
from pathlib import Path

from rocqipath.extraction._extraction_engine import (
    _write_region_manifest,
    _write_slide_manifest,
)
from rocqipath.extraction.patch_extraction import (
    PatchExtractionConfig,
    run_patch_extraction,
)
from rocqipath.registration.alignment import AlignmentConfig, run_alignment
from rocqipath.utils import discover_patch_pairs


def test_registration_dry_run_returns_discovered_pair(synthetic_registration_tree):
    fixture = synthetic_registration_tree
    results = run_alignment(
        AlignmentConfig(
            input_dir=str(fixture["root"]),
            output_dir=str(fixture["output"]),
            biomarker_folders=["CD8"],
            dry_run=True,
        )
    )

    assert len(results) == 1
    assert results[0].case.sample_id == "case01"
    assert results[0].case.hne_file == str(fixture["he"])
    assert results[0].case.ihc_file == str(fixture["ihc"])
    assert results[0].registrar is None


def test_patch_extraction_manifest_and_pair_discovery(synthetic_patch_dataset):
    fixture = synthetic_patch_dataset
    summary = run_patch_extraction(
        PatchExtractionConfig(
            he_dir=str(fixture["reference_root"]),
            aligned_dir=str(fixture["aligned_root"]),
            output_dir=str(fixture["output"]),
            biomarker_folders=["CD8"],
            ihc_channel_name="cd8",
            patch_size=4,
            stride=4,
            tissue_threshold=0.5,
            reference_source_magnification=20.0,
            target_source_magnification=20.0,
        )
    )

    assert summary["processed"] == 1
    assert summary["skipped"] == 0
    assert summary["cases"][0]["n_patches"] == 4

    case_dir = fixture["output"] / "patch_extraction" / "Sample_0001_CD8"
    manifest = json.loads((case_dir / "Sample_0001_CD8_metadata.json").read_text(encoding="utf-8"))
    assert manifest["dimensions"] == [8, 8]
    assert [patch["id"] for patch in manifest["patches"]] == [
        "000001",
        "000002",
        "000003",
        "000004",
    ]
    pairs = discover_patch_pairs(case_dir)
    assert len(pairs) == 4
    assert all(
        Path(reference).is_file() and Path(target).is_file()
        for reference, target, _patch_id in pairs
    )


def test_region_and_slide_manifests_round_trip(tmp_path: Path):
    region_path = tmp_path / "region_manifest.json"
    slide_path = tmp_path / "slide_manifest.json"
    _write_region_manifest(
        region_path,
        pipeline="tissue",
        sample_id="sample01",
        region_number=1,
        source_file="sample01.tif",
        rel_box={"rx": 0.1, "ry": 0.2, "rw": 0.3, "rh": 0.4},
        abs_box={"x": 10, "y": 20, "w": 30, "h": 40},
        full_slide_dims={"width": 100, "height": 100},
        detection_source="synthetic_mask",
    )
    _write_slide_manifest(
        slide_path,
        pipeline="tissue",
        sample_id="sample01",
        source_file="sample01.tif",
        n_regions=1,
        regions=[{"region_number": 1, "status": "saved"}],
    )

    region = json.loads(region_path.read_text(encoding="utf-8"))
    slide = json.loads(slide_path.read_text(encoding="utf-8"))
    assert region["coordinates"]["absolute_pixels"]["w"] == 30
    assert region["detection_source"] == "synthetic_mask"
    assert slide["n_regions"] == 1
    assert slide["regions"][0]["status"] == "saved"
