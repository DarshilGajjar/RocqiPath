"""Plain strip TIFFs must support multiple regions and previews."""

from pathlib import Path

import pytest

pytest.importorskip("pyvips")
pytest.importorskip("cv2")

from tests.golden import _data as D


def test_tissue_extraction_saves_every_region_from_strip_tiff(tmp_path: Path):
    import rocqipath as rp

    src = D.make_tissue_slides(tmp_path)
    result = rp.extract_tissue(src, tmp_path / "out", source_magnification=20)
    regions = result.summary["regions"]
    assert {name: len(found) for name, found in regions.items()} == {"slideA": 2, "slideB": 1}
    assert len(result.by_role("region")) == 3
    previews = sorted(p.name for p in (tmp_path / "out").rglob("*_preview.jpg"))
    assert previews == ["region_001_preview.jpg", "region_001_preview.jpg", "region_002_preview.jpg"]
