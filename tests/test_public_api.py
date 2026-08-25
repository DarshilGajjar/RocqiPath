"""Lock the documented RocqiPath import surface before structural changes."""

from __future__ import annotations

import rocqipath.analysis as analysis
import rocqipath.extraction as extraction
import rocqipath.registration as registration
import rocqipath.stain as stain
import rocqipath.visualization as visualization
from rocqipath.analysis import CellCountingConfig, PositiveCellCounter
from rocqipath.core import DEFAULT_TARGET_MAGNIFICATION, MagnificationPlan, OutputLayout
from rocqipath.core.exceptions import (
    ConfigurationError,
    DependencyError,
    ExtractionError,
    RegistrationError,
    RegistrationQualityError,
    SlideNotFoundError,
    UnsupportedFormatError,
    WSIProcessingError,
)
from rocqipath.extraction import (
    PatchExtractionConfig,
    ReversiblePatchExtractor,
    TMAExtractionConfig,
    TissueExtractionConfig,
    extract_tissue_regions,
    run_patch_extraction,
    run_tma_extraction_pipeline,
    run_tissue_pipeline,
)
from rocqipath.registration import (
    AlignmentConfig,
    AlignedCaseResult,
    OrbConfig,
    ValisConfig,
    WSIRegistrar,
    run_alignment,
)
from rocqipath.stain import (
    MacenkoNormalizer,
    ReinhardNormalizer,
    StainNormalizationConfig,
    VahadaneNormalizer,
    get_normalizer,
    run_stain_normalization_apply,
    run_stain_normalization_train,
)
from rocqipath.visualization import (
    IHCOverlayConfig,
    MarkerProfile,
    OverlayCombo,
    plot_selector_map,
    process_ihc_overlay,
    view_pairs,
)

EXPECTED_PUBLIC_SYMBOLS = {
    "analysis": {"CellCountingConfig", "PositiveCellCounter"},
    "extraction": {
        "PatchExtractionConfig",
        "ReversiblePatchExtractor",
        "TMAExtractionConfig",
        "TissueExtractionConfig",
        "extract_tissue_regions",
        "run_patch_extraction",
        "run_tma_extraction_pipeline",
        "run_tissue_pipeline",
    },
    "registration": {
        "AlignmentConfig",
        "AlignedCaseResult",
        "OrbConfig",
        "ValisConfig",
        "WSIRegistrar",
        "run_alignment",
    },
    "stain": {
        "MacenkoNormalizer",
        "ReinhardNormalizer",
        "StainNormalizationConfig",
        "VahadaneNormalizer",
        "get_normalizer",
        "run_stain_normalization_apply",
        "run_stain_normalization_train",
    },
    "visualization": {
        "IHCOverlayConfig",
        "MarkerProfile",
        "OverlayCombo",
        "plot_selector_map",
        "process_ihc_overlay",
        "view_pairs",
    },
}


def test_documented_imports_resolve() -> None:
    """Assert every documented public import resolves to a concrete object."""
    imported = [
        DEFAULT_TARGET_MAGNIFICATION,
        MagnificationPlan,
        OutputLayout,
        TissueExtractionConfig,
        PatchExtractionConfig,
        ReversiblePatchExtractor,
        TMAExtractionConfig,
        run_tissue_pipeline,
        run_patch_extraction,
        run_tma_extraction_pipeline,
        extract_tissue_regions,
        AlignmentConfig,
        AlignedCaseResult,
        run_alignment,
        ValisConfig,
        WSIRegistrar,
        StainNormalizationConfig,
        ReinhardNormalizer,
        MacenkoNormalizer,
        VahadaneNormalizer,
        get_normalizer,
        run_stain_normalization_train,
        run_stain_normalization_apply,
        PositiveCellCounter,
        CellCountingConfig,
        OrbConfig,
        IHCOverlayConfig,
        MarkerProfile,
        OverlayCombo,
        plot_selector_map,
        process_ihc_overlay,
        view_pairs,
        WSIProcessingError,
    ]
    assert all(symbol is not None for symbol in imported)


def test_subpackage_all_contracts_are_exact() -> None:
    """Assert feature subpackages export only their documented symbols."""
    packages = {
        "analysis": analysis,
        "extraction": extraction,
        "registration": registration,
        "stain": stain,
        "visualization": visualization,
    }
    assert {
        name: set(package.__all__) for name, package in packages.items()
    } == EXPECTED_PUBLIC_SYMBOLS


def test_exception_hierarchy_is_stable() -> None:
    """Assert every domain exception remains catchable via the public base."""
    direct = [
        ConfigurationError,
        SlideNotFoundError,
        UnsupportedFormatError,
        RegistrationError,
        ExtractionError,
        DependencyError,
    ]
    assert all(issubclass(error, WSIProcessingError) for error in direct)
    assert issubclass(RegistrationQualityError, RegistrationError)
    assert issubclass(SlideNotFoundError, FileNotFoundError)
    assert issubclass(DependencyError, ImportError)
