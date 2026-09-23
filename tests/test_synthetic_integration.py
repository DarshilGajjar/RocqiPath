"""Scanner-free integration tests for discovery, extraction, and manifests."""

from __future__ import annotations

import json
from pathlib import Path

import rocqipath as rp
from rocqipath.io import discover_patch_pairs
from rocqipath.io.manifest import write_region_manifest, write_slide_manifest


def test_registration_dry_run_discovers_pair_without_registering(synthetic_registration_tree):
    fixture = synthetic_registration_tree
    result = rp.align(
        fixture["root"],
        fixture["output"],
        pair_folders=["CD8"],
        reference_name="he",
        moving_name="cd8",
        dry_run=True,
    )

    # Dry runs log the discovered pairs but produce no aligned slides.
    assert len(result) == 0
    assert result.summary == {"cases": []}


def test_patch_extraction_manifest_and_pair_discovery(synthetic_patch_dataset):
    fixture = synthetic_patch_dataset
    result = rp.extract_patches(
        fixture["aligned_root"],
        fixture["output"],
        reference=fixture["reference_root"],
        biomarker_folders=["CD8"],
        reference_pattern=r"^(?P<sample_id>Sample_\d{4})_he\.tiff?$",
        moving_name="cd8",
        patch_size=4,
        stride=4,
        tissue_threshold=0.5,
        reference_source_magnification=20.0,
        target_source_magnification=20.0,
    )
    summary = result.summary

    assert summary["processed"] == 1
    assert summary["skipped"] == 0
    assert summary["cases"][0]["n_patches"] == 4
    assert len(result.by_role("patch")) == 8
    assert {item.meta["stain"] for item in result} == {"he", "cd8"}

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
    write_region_manifest(
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
    write_slide_manifest(
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
