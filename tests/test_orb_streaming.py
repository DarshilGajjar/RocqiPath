"""Regression coverage for bounded-memory, VALIS-free ORB export."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

import rocqipath.registration.core as core
from rocqipath.registration.core import WSIRegistrar


class _FakeSlide:
    dimensions = (128, 128)
    level_dimensions = ((128, 128),)
    level_downsamples = (1.0,)
    properties = {"openslide.mpp-x": "0.5", "openslide.mpp-y": "0.5"}

    def get_best_level_for_downsample(self, _downsample):
        return 0

    def read_region(self, _location, _level, size):
        return Image.new("RGB", size, (120, 80, 60))


def _registrar_for_stream_test() -> WSIRegistrar:
    registrar = object.__new__(WSIRegistrar)
    registrar.orb_matrix = np.eye(3, dtype=np.float64)
    registrar.orb_ref_scale_x = registrar.orb_ref_scale_y = 1.0
    registrar.orb_tgt_scale_x = registrar.orb_tgt_scale_y = 1.0
    registrar.slide_ref = _FakeSlide()
    registrar.slide_tgt = _FakeSlide()
    registrar.config = {"orb_save_tile_size": 64}
    return registrar


def test_orb_save_streams_tiles_without_full_canvas(tmp_path: Path, monkeypatch):
    created = []
    saves = []

    class FakeVipsImage:
        @classmethod
        def new_from_memory(cls, _data, width, height, bands, _format):
            created.append((width, height, bands))
            return cls()

        @classmethod
        def new_from_file(cls, _path, access=None):
            assert access == "sequential"
            return cls()

        @classmethod
        def arrayjoin(cls, images, across):
            assert len(images) == 4
            assert across == 2
            return cls()

        def write_to_file(self, path):
            Path(path).touch()

        def crop(self, _x, _y, _width, _height):
            return self

        def copy(self, **_kwargs):
            return self

        def set_type(self, *_args):
            pass

        def tiffsave(self, path, **kwargs):
            Path(path).touch()
            saves.append(kwargs)

    fake_pyvips = SimpleNamespace(
        Image=FakeVipsImage,
        GValue=SimpleNamespace(gstr_type="gstr"),
    )
    monkeypatch.setattr(core, "pyvips", fake_pyvips)
    monkeypatch.setattr(core, "HAS_PYVIPS", True)

    output = tmp_path / "aligned.ome.tiff"
    result = _registrar_for_stream_test()._save_orb_streamed(0, str(output))

    assert result == str(output)
    assert output.is_file()
    assert created == [(64, 64, 3)] * 4
    assert (128, 128, 3) not in created
    assert saves[0]["pyramid"] is True
    assert saves[0]["subifd"] is True


def test_orb_save_uses_inverse_registration_transform():
    registrar = _registrar_for_stream_test()
    registrar.orb_matrix = np.array([[1.0, 0.0, 10.0], [0.0, 1.0, 5.0], [0.0, 0.0, 1.0]])

    target_to_reference = registrar._orb_affine_for_level(0, 0)

    np.testing.assert_allclose(target_to_reference[:2, 2], [-10.0, -5.0])
