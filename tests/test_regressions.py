"""Regression tests for defects found in review."""

import pytest

from rocqipath.errors import ExtractionError
from rocqipath.extraction.config import ExtractPatchesConfig


def test_replace_keeps_fields_assigned_after_construction():
    config = ExtractPatchesConfig()
    config.patch_size = 256
    changed = config.replace(tissue_threshold=0.5)
    assert changed.patch_size == 256
    assert changed.stride == 256  # still derived from the new patch size


def test_stain_outputs_with_the_same_file_name_do_not_collide(tmp_path):
    from rocqipath.stain.batch import output_paths

    inputs = [tmp_path / "slideA" / "core_001.png", tmp_path / "slideB" / "core_001.png"]
    for path in inputs:
        path.parent.mkdir()
        path.touch()
    outputs = [out for _source, out in output_paths(inputs, ["all"], tmp_path / "out")]
    assert len(set(outputs)) == 2


def test_patch_extraction_raises_when_every_case_fails(tmp_path):
    from rocqipath.extraction.patches import extract_case_patches

    cases = [("case1", "missing_he.tif", "missing_cd8.tif", "cd8")]
    with pytest.raises(ExtractionError, match="case1"):
        extract_case_patches(cases, str(tmp_path), ExtractPatchesConfig())


def test_count_batch_raises_when_every_slide_fails(tmp_path):
    from rocqipath.counting.config import CountCellsConfig
    from rocqipath.counting.counter import PositiveCellCounter

    (tmp_path / "broken.svs").write_text("not a slide")
    counter = PositiveCellCounter(CountCellsConfig(), output_dir=str(tmp_path / "out"))
    with pytest.raises(ExtractionError, match="broken.svs"):
        counter.count_batch(str(tmp_path))
