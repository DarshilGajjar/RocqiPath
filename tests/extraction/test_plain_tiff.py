"""Plain strip TIFFs must support multiple regions and previews."""

from pathlib import Path

import pytest

pytest.importorskip("pyvips")
pytest.importorskip("cv2")

from tests.golden import _data as D


def test_tissue_extraction_saves_every_region_from_strip_tiff(tmp_path: Path):
    from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

    src = D.make_tissue_slides(tmp_path)
    results = run_tissue_pipeline(
        str(src), str(tmp_path / "out"), TissueExtractionConfig(source_magnification=20)
    )
    assert {name: len(regions) for name, regions in results.items()} == {"slideA": 2, "slideB": 1}
    previews = sorted(p.name for p in (tmp_path / "out").rglob("*_preview.jpg"))
    assert previews == ["region_001_preview.jpg", "region_001_preview.jpg", "region_002_preview.jpg"]
