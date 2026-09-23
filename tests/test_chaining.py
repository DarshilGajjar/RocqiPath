"""Workflows chain through Result objects and rocqipath.json output folders."""

from __future__ import annotations

import json
import shutil

import pytest

import rocqipath as rp
from rocqipath.io.inputs import resolve_inputs
from rocqipath.io.manifest import RUN_MANIFEST, read_run_manifest
from tests.golden import _data as D

pytest.importorskip("pyvips")
pytest.importorskip("openslide")
pytest.importorskip("cv2")

ALIGN = dict(
    pair_folders=["CD8"],
    reference_name="he",
    moving_name="cd8",
    backend="orb",
    reference_source_magnification=D.SOURCE_MAG,
    moving_source_magnification=D.SOURCE_MAG,
    target_magnification=D.SOURCE_MAG,
)
PATCHES = dict(
    patch_size=128,
    tissue_threshold=0.5,
    moving_name="cd8",
    reference_source_magnification=D.SOURCE_MAG,
)


@pytest.fixture(scope="module")
def aligned(tmp_path_factory):
    root = tmp_path_factory.mktemp("chain")
    return rp.align(D.make_alignment_pair(root), root / "aligned", **ALIGN)


def test_every_run_records_a_manifest(aligned):
    assert aligned.manifest_path == aligned.output_dir / RUN_MANIFEST
    manifest = json.loads(aligned.manifest_path.read_text())
    assert manifest["schema"] == 1
    run = manifest["runs"]["align"]
    assert run["config"]["backend"] == "orb"
    aligned_paths = [i["path"] for i in run["items"] if i["role"] == "aligned"]
    assert aligned_paths == ["alignment/case01_cd8/case01_cd8_aligned_moving.ome.tiff"]


def test_manifest_round_trips_to_equal_results(aligned):
    (restored,) = read_run_manifest(aligned.output_dir)
    assert restored.items == aligned.items
    assert restored.config == aligned.config


def test_align_result_feeds_patch_extraction_without_staging(aligned, tmp_path):
    from_result = rp.extract_patches(aligned, tmp_path / "a", **PATCHES)
    from_folder = rp.extract_patches(aligned.output_dir, tmp_path / "b", **PATCHES)
    assert from_result.summary["processed"] == 1
    assert from_result.summary["cases"][0]["case_id"] == "case01_CD8"
    names = lambda r: sorted(item.path.name for item in r)  # noqa: E731
    assert names(from_result) == names(from_folder)
    assert {item.meta["stain"] for item in from_result} == {"he", "cd8"}


def test_align_result_feeds_cell_counting(aligned, tmp_path):
    counts = rp.count_cells(aligned, tmp_path, source_magnification=D.SOURCE_MAG, patch_size=256)
    assert [r["slide"] for r in counts.summary["results"]] == ["case01_cd8_aligned_moving.ome.tiff"]


def test_moved_output_folder_still_resolves(aligned, tmp_path):
    moved = tmp_path / "moved"
    shutil.copytree(aligned.output_dir, moved)
    items = resolve_inputs(moved, roles=("aligned",))
    assert [item.path for item in items] == [
        moved / "alignment" / "case01_cd8" / "case01_cd8_aligned_moving.ome.tiff"
    ]


def test_wrong_roles_are_explained(aligned, tmp_path):
    with pytest.raises(ValueError, match="the align result holds aligned, figure, reference files; this workflow needs one of: patch, region, core"):
        rp.normalize_stain(aligned, tmp_path, normalizer=tmp_path / "w.npz")


def test_failed_run_writes_no_manifest(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(TypeError, match="needs the output of rp.align"):
        rp.extract_patches(empty, tmp_path / "out")  # no reference=, no align result
    assert not (tmp_path / "out" / RUN_MANIFEST).exists()


def test_patches_feed_stain_normalization(aligned, tmp_path):
    pytest.importorskip("tiatoolbox")
    patches = rp.extract_patches(aligned, tmp_path / "patches", **PATCHES)
    weights = rp.train_stain_normalizer(patches, tmp_path / "stain", method="reinhard", stains=["he"])
    normalized = rp.normalize_stain(patches, tmp_path / "stain", normalizer=weights, stains=["he"])
    he_patches = [item for item in patches if item.meta["stain"] == "he"]
    assert normalized.summary["processed"] == len(he_patches) > 0
