"""Lock the public import surface: Tier 1 (``rocqipath``) and Tier 2 packages."""

from __future__ import annotations

import importlib
import inspect

import pytest

import rocqipath as rp

TIER_1 = {
    "__version__",
    # workflows
    "align",
    "compare",
    "count_cells",
    "extract_patches",
    "extract_tissue",
    "extract_tma",
    "normalize_stain",
    "overlay_markers",
    "train_stain_normalizer",
    # running and results
    "run",
    "list_workflows",
    "Result",
    "Item",
    "open_slide",
    "set_log_level",
    # configs
    "AlignConfig",
    "OrbOptions",
    "ValisOptions",
    "CompareConfig",
    "CountCellsConfig",
    "ExtractPatchesConfig",
    "ExtractTMAConfig",
    "ExtractTissueConfig",
    "MarkerProfile",
    "OverlayCombo",
    "OverlayConfig",
    "StainConfig",
    # errors
    "ConfigurationError",
    "DependencyError",
    "ExtractionError",
    "RegistrationError",
    "RegistrationQualityError",
    "RocqiPathError",
    "SlideNotFoundError",
    "UnsupportedFormatError",
}

TIER_2 = {
    "rocqipath.alignment": {"AlignConfig", "AlignedCaseResult", "OrbOptions", "ValisOptions", "WSIRegistrar"},
    "rocqipath.counting": {"CountCellsConfig", "PositiveCellCounter"},
    "rocqipath.extraction": {
        "ExtractPatchesConfig",
        "ExtractTMAConfig",
        "ExtractTissueConfig",
        "ReversiblePatchExtractor",
        "extract_patches_single",
        "extract_tissue_regions",
    },
    "rocqipath.stain": {
        "MacenkoNormalizer",
        "ReinhardNormalizer",
        "StainConfig",
        "VahadaneNormalizer",
        "get_normalizer",
    },
    "rocqipath.viz": {
        "CompareConfig",
        "MarkerProfile",
        "OverlayCombo",
        "OverlayConfig",
        "export_grid_map",
        "export_paired_grid_maps",
        "export_wsi_thumbnails",
        "plot_selector_map",
        "view_pairs",
    },
}


def test_tier_one_surface_is_exact() -> None:
    assert set(rp.__all__) == TIER_1
    assert set(dir(rp)) >= TIER_1 - {"__version__"}


@pytest.mark.parametrize("name", sorted(TIER_1 - {"__version__"}))
def test_tier_one_names_resolve(name: str) -> None:
    assert getattr(rp, name) is not None


@pytest.mark.parametrize("package", sorted(TIER_2))
def test_tier_two_surfaces_are_exact_and_resolve(package: str) -> None:
    module = importlib.import_module(package)
    assert set(module.__all__) == TIER_2[package]
    for name in module.__all__:
        assert getattr(module, name) is not None


def test_workflows_share_one_calling_convention() -> None:
    for workflow in rp.list_workflows():
        parameters = list(inspect.signature(workflow.function).parameters.values())
        assert [p.name for p in parameters[:3]] == ["inputs", "output_dir", "config"]
        assert parameters[-1].kind is inspect.Parameter.VAR_KEYWORD
        assert getattr(rp, workflow.name) is workflow.function


def test_unknown_keyword_suggests_a_field(tmp_path) -> None:
    with pytest.raises(TypeError, match="did you mean 'target_magnification'"):
        rp.extract_tissue(tmp_path, tmp_path / "out", target_magnificaton=10)


def test_config_without_defaults_explains_what_is_missing(tmp_path) -> None:
    with pytest.raises(TypeError, match="OverlayConfig has no default for markers"):
        rp.overlay_markers(tmp_path, tmp_path / "out")


def test_run_accepts_command_spelling(tmp_path) -> None:
    with pytest.raises(KeyError, match="Did you mean 'count_cells'"):
        rp.run("count-cell", tmp_path, tmp_path / "out")


def test_exception_hierarchy_is_stable() -> None:
    direct = [
        rp.ConfigurationError,
        rp.SlideNotFoundError,
        rp.UnsupportedFormatError,
        rp.RegistrationError,
        rp.ExtractionError,
        rp.DependencyError,
    ]
    assert all(issubclass(error, rp.RocqiPathError) for error in direct)
    assert issubclass(rp.RegistrationQualityError, rp.RegistrationError)
    assert issubclass(rp.SlideNotFoundError, FileNotFoundError)


def test_open_slide_reports_missing_files(tmp_path) -> None:
    with pytest.raises(rp.SlideNotFoundError):
        rp.open_slide(tmp_path / "missing.svs")
