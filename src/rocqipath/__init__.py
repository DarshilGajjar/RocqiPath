"""RocqiPath: modular whole-slide image processing for computational pathology."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _distribution_version

from .core.exceptions import *  # noqa: F403
from .core.magnification import (
    DEFAULT_TARGET_MAGNIFICATION as DEFAULT_TARGET_MAGNIFICATION,
    MagnificationPlan as MagnificationPlan,
)
from .core.output import OutputLayout as OutputLayout
from .study import (
    Recipe as Recipe,
    Selection as Selection,
    SlideRecord as SlideRecord,
    Study as Study,
    StudyDescriptor as StudyDescriptor,
    StudyPaths as StudyPaths,
)

try:
    __version__ = _distribution_version("rocqipath")
except _PackageNotFoundError:
    __version__ = "0+unknown"


# Extraction remains available at the top level.
try:
    from .extraction import (  # noqa: F401
        CoreExtractionConfig,
        PatchExtractionConfig,
        TMAExtractionConfig,
        TissueExtractionConfig,
        run_core_extraction_pipeline,
        run_patch_extraction,
        run_tma_extraction_pipeline,
        run_tissue_pipeline,
    )
except ImportError:
    pass


try:
    from .stain import StainNormalizationConfig  # noqa: F401
except ImportError:
    pass


# Registration is intentionally lazy because importing VALIS may initialize
# neural feature models such as LightGlue.
_REGISTRATION_EXPORTS = {
    "AlignmentConfig",
    "run_alignment",
    "ValisConfig",
    "WSIRegistrar",
}


def __getattr__(name: str):
    """Load registration APIs only when they are explicitly requested."""

    if name in _REGISTRATION_EXPORTS:
        from . import registration

        try:
            value = getattr(registration, name)
        except AttributeError as exc:
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}. "
                "The optional registration dependencies may not be installed."
            ) from exc

        globals()[name] = value
        return value

    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    return sorted(
        set(globals()) | _REGISTRATION_EXPORTS
    )