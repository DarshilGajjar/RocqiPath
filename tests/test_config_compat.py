"""Typed configs: re-exports, round trips, overrides and validation messages."""

from __future__ import annotations

from dataclasses import fields

import pytest

import rocqipath as rp
import rocqipath.alignment as alignment
import rocqipath.extraction as extraction
import rocqipath.stain as stain
import rocqipath.viz as viz
from rocqipath._internal.base_config import field_help
from rocqipath.errors import ConfigurationError

ALL_CONFIGS = [
    rp.ExtractTissueConfig,
    rp.ExtractTMAConfig,
    rp.ExtractPatchesConfig,
    rp.AlignConfig,
    rp.ValisOptions,
    rp.OrbOptions,
    rp.StainConfig,
    rp.CountCellsConfig,
    rp.CompareConfig,
    rp.OverlayConfig,
    rp.MarkerProfile,
    rp.OverlayCombo,
]


def test_packages_reexport_the_same_config_classes() -> None:
    assert alignment.AlignConfig is rp.AlignConfig
    assert alignment.ValisOptions is rp.ValisOptions
    assert extraction.ExtractTissueConfig is rp.ExtractTissueConfig
    assert extraction.ExtractPatchesConfig is rp.ExtractPatchesConfig
    assert stain.StainConfig is rp.StainConfig
    assert viz.OverlayConfig is rp.OverlayConfig
    assert viz.MarkerProfile is rp.MarkerProfile


@pytest.mark.parametrize("config", ALL_CONFIGS, ids=lambda c: c.__name__)
def test_every_field_is_documented(config) -> None:
    undocumented = [f.name for f in fields(config) if f.name not in field_help(config)]
    assert undocumented == []


@pytest.mark.parametrize("config", ALL_CONFIGS, ids=lambda c: c.__name__)
def test_no_config_holds_input_or_output_roots(config) -> None:
    names = {f.name for f in fields(config)}
    assert not names & {"input_dir", "output_dir", "he_dir", "aligned_dir", "save_dir", "base_output_dir"}


def test_overlay_config_round_trips_nested_values() -> None:
    config = rp.OverlayConfig(
        markers={"cd8": rp.MarkerProfile(color=(1, 2, 3))},
        combinations=[rp.OverlayCombo(base="cd8", overlays=["cd8"])],
        base_marker="cd8",
    )
    restored = rp.OverlayConfig.from_dict(config.to_dict())
    assert restored.to_dict() == config.to_dict()
    assert dict(config.describe())["Base Marker"] == "cd8"


def test_align_config_round_trips_nested_backends() -> None:
    config = rp.AlignConfig(backend="orb").replace(orb__ransac_threshold=7.5, valis__num_features=3000)
    restored = rp.AlignConfig.from_dict(config.to_dict())
    assert (restored.orb.ransac_threshold, restored.valis.num_features) == (7.5, 3000)


def test_replace_rederives_dependent_fields() -> None:
    assert "cd8" in rp.AlignConfig().replace(reference_name="he", moving_name="cd8").filename_pattern
    assert rp.ExtractPatchesConfig().replace(patch_size=64).stride == 64
    assert rp.ExtractPatchesConfig(stride=32).replace(patch_size=64).stride == 32


def test_unknown_fields_suggest_the_closest_name() -> None:
    with pytest.raises(TypeError, match="did you mean 'backend'"):
        rp.AlignConfig().replace(bakend="orb")


def test_toml_loading(tmp_path) -> None:
    path = tmp_path / "align.toml"
    path.write_text('backend = "orb"\nqc_enabled = true\n[orb]\nransac_threshold = 9.0\n')
    config = rp.AlignConfig.from_toml(path)
    assert (config.backend, config.qc_enabled, config.orb.ransac_threshold) == ("orb", True, 9.0)


def test_orb_defaults_match_what_the_backend_always_used() -> None:
    settings = rp.OrbOptions().registrar_settings()
    assert settings["ransac_threshold"] == 20.0
    assert settings["orb_thumb_size"] == 1500


@pytest.mark.parametrize(
    ("factory", "error_type", "message"),
    [
        (
            lambda: rp.AlignConfig(reference_name="he", moving_name="HE"),
            ValueError,
            "reference_name and moving_name must differ; both were 'he'.",
        ),
        (
            lambda: rp.StainConfig(method="unknown"),
            ConfigurationError,
            "method must be one of ['macenko', 'reinhard', 'vahadane']; got 'unknown'",
        ),
        (
            lambda: rp.CompareConfig(random_rois=11),
            ValueError,
            "random_rois must be between 0 and 10",
        ),
    ],
)
def test_validation_messages(factory, error_type, message) -> None:
    with pytest.raises(error_type) as caught:
        factory()
    assert str(caught.value) == message
