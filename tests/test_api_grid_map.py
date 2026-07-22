"""Regression coverage for the public grid-map result contract."""

from pathlib import Path

from PIL import Image

import rocqipath.api as api


def test_grid_map_rejects_unknown_extension_without_subscripting_format(tmp_path: Path):
    source = tmp_path / "slide.txt"
    source.write_text("not a slide", encoding="utf-8")

    assert api.generate_single_grid_map_for_slide(
        str(source), str(tmp_path / "maps"), {"grid_density": 2}
    ) == (False, None, "Unsupported WSI format")


def test_grid_map_success_contract_and_cleanup(tmp_path: Path, monkeypatch):
    source = tmp_path / "slide.svs"
    source.write_bytes(b"synthetic")
    closed = []

    class FakeRegistrar:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_grid_map(self):
            return Image.new("RGB", (8, 8), "white"), [0]

        def close(self):
            closed.append(True)

    def fake_plot(_thumb, _grids, _rows, _cols, output_path, *, show):
        assert show is False
        Path(output_path).write_bytes(b"png")

    monkeypatch.setattr(api, "_HAS_CORE", True)
    monkeypatch.setattr(api, "_HAS_VISUALIZATION", True)
    monkeypatch.setattr(api, "WSIRegistrar", FakeRegistrar)
    monkeypatch.setattr(api, "plot_selector_map", fake_plot)

    success, map_path, reason = api.generate_single_grid_map_for_slide(
        str(source), str(tmp_path / "maps"), {"grid_density": 2}
    )

    assert success is True
    assert reason is None
    assert Path(map_path).is_file()
    assert closed == [True]
