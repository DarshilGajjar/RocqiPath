"""Compatibility coverage for typed and legacy configuration inputs."""

from __future__ import annotations

from dataclasses import asdict

import pytest

import rocqipath.config as legacy_config
import rocqipath.extraction as extraction
import rocqipath.registration as registration
import rocqipath.stain as stain
import rocqipath.visualization as visualization
from rocqipath.analysis.counting import (
    CellCountingConfig,
    PositiveCellCounter,
)
from rocqipath.config import (
    AlignmentConfig,
    IHCOverlayConfig,
    MarkerProfile,
    OverlayCombo,
    PatchExtractionConfig,
    StainNormalizationConfig,
    TMAExtractionConfig,
    TissueExtractionConfig,
    ValisConfig,
)
from rocqipath.core.exceptions import ConfigurationError


def test_default_config_is_computed_from_typed_defaults() -> None:
    """Return a fresh deprecated mapping derived from the dataclass."""
    with pytest.warns(DeprecationWarning):
        first = legacy_config.DEFAULT_CONFIG
    with pytest.warns(DeprecationWarning):
        second = legacy_config.DEFAULT_CONFIG

    assert first == asdict(legacy_config.RegistrarDefaults())
    assert first is not second


def test_cell_counter_accepts_equivalent_dict_and_dataclass(
    tmp_path,
    capsys,
) -> None:
    """Resolve legacy mappings and typed configs to identical state."""
    values = {
        "patch_size": "64",
        "tissue_threshold": "0.25",
        "magnification": "10",
        "output_dir": str(tmp_path),
        "min_cell_area": "5",
        "max_cell_area": "12",
    }
    from_dict = PositiveCellCounter(values)
    capsys.readouterr()
    typed = PositiveCellCounter(CellCountingConfig.from_dict(values))
    capsys.readouterr()

    fields = (
        "patch_size",
        "tissue_threshold",
        "target_magnification",
        "output_dir",
        "min_cell_area",
        "max_cell_area",
    )
    assert {field: getattr(from_dict, field) for field in fields} == {
        field: getattr(typed, field) for field in fields
    }


def test_feature_packages_reexport_central_config_classes() -> None:
    """Keep feature imports stable while config owns each class."""
    assert registration.AlignmentConfig is AlignmentConfig
    assert registration.ValisConfig is ValisConfig
    assert extraction.TissueExtractionConfig is TissueExtractionConfig
    assert extraction.TMAExtractionConfig is TMAExtractionConfig
    assert extraction.PatchExtractionConfig is PatchExtractionConfig
    assert stain.StainNormalizationConfig is StainNormalizationConfig
    assert visualization.IHCOverlayConfig is IHCOverlayConfig
    assert visualization.MarkerProfile is MarkerProfile
    assert visualization.OverlayCombo is OverlayCombo


def test_base_config_round_trips_nested_overlay_config(tmp_path) -> None:
    """Serialize and restore nested config dataclasses without losing values."""
    config = IHCOverlayConfig(
        markers={"cd8": MarkerProfile(color=(1, 2, 3))},
        combinations=[OverlayCombo(base="cd8", overlays=["cd8"])],
        base_marker="cd8",
        save_dir=str(tmp_path),
    )

    restored = IHCOverlayConfig.from_dict(config.to_dict())

    assert restored.to_dict() == config.to_dict()
    assert dict(config.describe())["Base Marker"] == "cd8"


@pytest.mark.parametrize(
    ("factory", "error_type", "message"),
    [
        (
            lambda: AlignmentConfig(reference_name="he", moving_name="HE"),
            ValueError,
            "reference_name and moving_name must differ; both were 'he'.",
        ),
        (
            lambda: PatchExtractionConfig(
                he_dir="he",
                aligned_dir="aligned",
                output_dir="out",
                biomarker_folders=[],
            ),
            ValueError,
            "biomarker_folders must be a non-empty list.",
        ),
        (
            lambda: StainNormalizationConfig(n_type="unknown"),
            ConfigurationError,
            "n_type must be one of ['macenko', 'reinhard', 'vahadane']; got 'unknown'",
        ),
    ],
)
def test_centralized_configs_preserve_validation_messages(
    factory,
    error_type,
    message,
) -> None:
    """Keep user-facing validation errors stable after relocation."""
    with pytest.raises(error_type, match=None) as caught:
        factory()
    assert str(caught.value) == message
