"""Regression checks for stain weights independent of optional model backends."""

import numpy as np
import pytest
from types import SimpleNamespace

from rocqipath.stain.normalizers import StainNormalizerBase
from rocqipath.stain import normalizers
from rocqipath.core.exceptions import ExtractionError


def test_macenko_restores_scaling_from_legacy_concentrations(tmp_path):
    path = tmp_path / "legacy.npz"
    concentrations = np.arange(20, dtype=float).reshape(10, 2)
    np.savez(path, sm=np.ones((2, 3)), tc=concentrations)
    restored = object.__new__(normalizers.MacenkoNormalizer)
    restored._norm = SimpleNamespace(maxC_target=None)
    restored.load_weights(path)
    np.testing.assert_array_equal(
        restored._norm.maxC_target, np.percentile(concentrations, 99, axis=0).reshape(1, 2)
    )


def test_vahadane_round_trip_preserves_concentration_scaling(tmp_path):
    fitted = object.__new__(normalizers.VahadaneNormalizer)
    fitted.stain_matrix_target = np.ones((2, 3))
    fitted._norm = SimpleNamespace(maxC_target=np.array([[1.5, 2.5]]))
    path = tmp_path / "weights.npz"
    fitted.save_weights(path)
    restored = object.__new__(normalizers.VahadaneNormalizer)
    restored._norm = SimpleNamespace(maxC_target=None)
    restored.load_weights(path)
    np.testing.assert_array_equal(restored._norm.maxC_target, fitted._norm.maxC_target)


def test_legacy_vahadane_archive_requests_retraining(tmp_path):
    path = tmp_path / "legacy.npz"
    np.savez(path, sm=np.ones((2, 3)))
    restored = object.__new__(normalizers.VahadaneNormalizer)
    restored._norm = SimpleNamespace(maxC_target=None)
    with pytest.raises(ExtractionError, match="[Rr]etrain"):
        restored.load_weights(path)


@pytest.mark.skipif(not normalizers._TIATOOLBOX_AVAILABLE, reason="requires TIAToolbox")
@pytest.mark.parametrize("name", ["reinhard", "macenko", "vahadane"])
def test_fitted_normalizer_matches_freshly_loaded_normalizer(tmp_path, name):
    rng = np.random.default_rng(42)
    target = rng.integers(30, 220, (32, 32, 3), dtype=np.uint8)
    source = rng.integers(40, 240, (32, 32, 3), dtype=np.uint8)
    fitted = normalizers.get_normalizer(name).fit(target)
    expected = fitted.transform(source)
    path = tmp_path / "weights.npz"
    fitted.save_weights(path)
    restored = normalizers.get_normalizer(name).load_weights(path)
    np.testing.assert_array_equal(restored.transform(source), expected)


@pytest.mark.parametrize("filename", ["weights.npz", "weights", "weights.custom"])
def test_weight_archive_round_trip_uses_exact_requested_path(tmp_path, filename):
    path = tmp_path / filename
    expected = np.array([1.0, 2.0, 3.0])
    saved = StainNormalizerBase._save_archive(path, means=expected)
    assert saved.is_file()
    _, archive = StainNormalizerBase._load_archive(path, "Missing: {path}")
    with archive:
        np.testing.assert_array_equal(archive["means"], expected)
