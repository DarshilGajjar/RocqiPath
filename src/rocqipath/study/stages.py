"""Stage adapters: translate a recipe into calls on the existing pipelines.

Nothing here re-implements image processing.  Each adapter does three things:

1. resolve its inputs from the slide index rather than from a directory
   argument the user had to remember;
2. build the existing typed config from the resolved recipe;
3. call the existing pipeline entry point and record what it produced.

This is the integration seam.  If a pipeline signature changes, this file is
the only place a study needs updating — and the original functions remain
callable directly, exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.study.index import SlideRecord, derive_pairs
from rocqipath.study.paths import StudyPaths
from rocqipath.study.recipe import Recipe
from rocqipath.study.staging import stage_pairs, stage_slides

__all__ = ["STAGE_ORDER", "StageResult", "run_stage", "stage_dependencies"]

#: Execution order.  Later stages consume earlier stages' output.
STAGE_ORDER = ("tissue", "alignment", "patches", "stain", "counts")

#: What each stage needs to have run before it.
_DEPENDENCIES: Dict[str, tuple] = {
    "tissue": (),
    "alignment": (),
    "patches": ("alignment",),
    "stain": ("patches",),
    "counts": ("patches",),
}


def stage_dependencies(stage: str) -> tuple:
    """Return the stages that must run before ``stage``.

    Parameters
    ----------
    stage : str
        Stage name.

    Returns
    -------
    tuple of str
        Prerequisite stage names, possibly empty.

    Raises
    ------
    ConfigurationError
        If ``stage`` is not a known stage.
    """
    if stage not in _DEPENDENCIES:
        raise ConfigurationError(
            f"Unknown stage {stage!r}. Known stages: {', '.join(STAGE_ORDER)}."
        )
    return _DEPENDENCIES[stage]


@dataclass
class StageResult:
    """What one stage did.

    Attributes
    ----------
    stage : str
        Stage name.
    status : {"completed", "skipped", "planned", "failed"}
        ``planned`` is returned for a dry run.
    output_dir : str
        Where the stage wrote, or would write.
    n_items : int
        Slides, pairs, or cases the stage acted on.
    recipe_hash : str
        Recipe the stage ran under.
    detail : dict
        Stage-specific values, including the resolved config.
    warnings : list of str
        Non-fatal problems.
    error : str, optional
        Why the stage failed.
    """

    stage: str
    status: str
    output_dir: str = ""
    n_items: int = 0
    recipe_hash: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Return whether the stage did not fail."""
        return self.status != "failed"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this result."""
        return {
            "stage": self.stage,
            "status": self.status,
            "output_dir": self.output_dir,
            "n_items": self.n_items,
            "recipe_hash": self.recipe_hash,
            "detail": self.detail,
            "warnings": self.warnings,
            "error": self.error,
        }


def _active(records: Sequence[SlideRecord]) -> List[SlideRecord]:
    """Return indexed slides that are neither excluded nor missing."""
    return [item for item in records if not item.excluded and item.exists]


def _usable(records: Sequence[SlideRecord], recipe: Recipe) -> List[SlideRecord]:
    """Return slides the recipe marked usable, or all when unknown."""
    usable: List[SlideRecord] = []
    for record in _active(records):
        entry = recipe.slides.get(record.slide_uid)
        if entry is None or entry.get("usable", True):
            usable.append(record)
    return usable


def _source_magnifications(records: Sequence[SlideRecord]) -> Dict[str, float]:
    """Collect declared fallback magnifications, keyed by stain."""
    values: Dict[str, float] = {}
    for record in records:
        if record.source_magnification:
            values.setdefault(record.stain, float(record.source_magnification))
    return values


def _run_tissue(
    paths: StudyPaths,
    recipe: Recipe,
    records: Sequence[SlideRecord],
    *,
    dry_run: bool,
    link_mode: str,
) -> StageResult:
    """Stage slides and run WSI or TMA tissue extraction."""
    settings = recipe.stage("tissue")
    slides = _usable(records, recipe)
    output = paths.stage_dir("tissue", create=not dry_run)
    result = StageResult(
        stage="tissue",
        status="planned",
        output_dir=str(paths.root),
        n_items=len(slides),
        recipe_hash=recipe.recipe_hash,
        detail={"mode": settings.get("mode", "wsi"), "settings": dict(settings)},
    )
    if not slides:
        result.status = "skipped"
        result.warnings.append("No usable slides for tissue extraction.")
        return result
    if dry_run:
        return result

    staged = stage_slides(slides, paths.staging / "tissue", link_mode=link_mode)
    result.warnings.extend(staged.warnings)
    fallbacks = _source_magnifications(slides)
    shared = dict(
        target_magnification=float(settings["target_magnification"]),
        detection_magnification=float(settings["detection_magnification"]),
        source_magnification=(next(iter(fallbacks.values()), None)),
        min_area_fraction=float(settings["min_area_fraction"]),
        preview_scale=float(settings.get("preview_scale", 0.2)),
        tif_compression=str(settings.get("tif_compression", "lzw")),
        tif_quality=int(settings.get("tif_quality", 99)),
        skip_existing=bool(settings.get("skip_existing", True)),
    )

    if str(settings.get("mode", "wsi")).lower() == "tma":
        from rocqipath.extraction import TMAExtractionConfig, run_tma_extraction_pipeline

        config = TMAExtractionConfig(**shared)
        run_tma_extraction_pipeline(
            input_dir=str(staged.root),
            output_root=str(paths.root),
            cfg=config,
            target_stains=list(settings.get("target_stains", ["all"])),
        )
    else:
        from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

        config = TissueExtractionConfig(**shared)
        run_tissue_pipeline(str(staged.root), str(paths.root), config)

    result.status = "completed"
    result.output_dir = str(output)
    result.detail["staged"] = len(staged.entries)
    return result


def _run_alignment(
    paths: StudyPaths,
    recipe: Recipe,
    records: Sequence[SlideRecord],
    *,
    dry_run: bool,
    link_mode: str,
) -> StageResult:
    """Stage derived pairs and run registration."""
    settings = recipe.stage("alignment")
    pairs = derive_pairs(_usable(records, recipe), biomarkers=settings.get("moving_stains"))
    output = paths.stage_dir("alignment", create=not dry_run)
    result = StageResult(
        stage="alignment",
        status="planned",
        output_dir=str(output),
        n_items=len(pairs),
        recipe_hash=recipe.recipe_hash,
        detail={
            "method": settings.get("method", "valis"),
            "pairs": [pair.pair_uid for pair in pairs],
            "settings": dict(settings),
        },
    )
    if not pairs:
        result.status = "skipped"
        result.warnings.append("No reference/moving pairs could be derived.")
        return result
    if dry_run:
        return result

    staged = stage_pairs(pairs, paths.staging / "alignment", link_mode=link_mode)
    result.warnings.extend(staged.warnings)

    from rocqipath.registration import AlignmentConfig, run_alignment

    config = AlignmentConfig(
        input_dir=str(staged.root),
        output_dir=str(paths.root),
        pair_folders=sorted({pair.biomarker for pair in pairs}),
        alignment_method=str(settings.get("method", "valis")),
        target_magnification=float(settings["target_magnification"]),
        patch_size=int(settings.get("patch_size", 1024)),
        grid_density=int(settings.get("grid_density", 1)),
        qc_enabled=bool(settings.get("qc_enabled", True)),
        qc_output_dir=str(paths.qc),
        keep_valis_diagnostics=bool(settings.get("keep_diagnostics", True)),
    )
    run_alignment(config)

    result.status = "completed"
    result.detail["staged"] = len(staged.entries)
    return result


def _run_patches(
    paths: StudyPaths,
    recipe: Recipe,
    records: Sequence[SlideRecord],
    *,
    dry_run: bool,
    link_mode: str,
) -> StageResult:
    """Extract paired patches from aligned output, measuring but not filtering."""
    settings = recipe.stage("patches")
    pairs = derive_pairs(_usable(records, recipe), biomarkers=settings.get("moving_stains"))
    output = paths.stage_dir("patches", create=not dry_run)
    biomarkers = sorted({pair.biomarker for pair in pairs})
    result = StageResult(
        stage="patches",
        status="planned",
        output_dir=str(output),
        n_items=len(pairs),
        recipe_hash=recipe.recipe_hash,
        detail={"biomarkers": biomarkers, "settings": dict(settings)},
    )
    if not pairs:
        result.status = "skipped"
        result.warnings.append("No pairs available for patch extraction.")
        return result

    alignment_dir = paths.stage_dir("alignment", create=False)
    aligned_present = alignment_dir.is_dir() and any(alignment_dir.iterdir())
    if not dry_run and not aligned_present:
        result.status = "failed"
        result.error = (
            "Patch extraction needs aligned output. Run: rocqipath study run <name> "
            "--stage alignment"
        )
        return result
    if dry_run:
        return result

    references = [pair.reference for pair in pairs]
    staged = stage_slides(
        {record.slide_uid: record for record in references}.values(),
        paths.staging / "patches",
        link_mode=link_mode,
    )
    result.warnings.extend(staged.warnings)

    from rocqipath.extraction import PatchExtractionConfig, run_patch_extraction

    reference_stain = str(settings.get("reference_stain", "he"))
    config = PatchExtractionConfig(
        he_dir=str(staged.root),
        aligned_dir=str(alignment_dir),
        output_dir=str(paths.root),
        biomarker_folders=biomarkers,
        reference_name=reference_stain,
        patch_size=int(settings["patch_size"]),
        stride=int(settings.get("stride") or settings["patch_size"]),
        tissue_threshold=float(settings.get("tissue_threshold", 0.0)),
        target_magnification=float(settings["target_magnification"]),
        dimension_tolerance=float(settings.get("dimension_tolerance", 0.01)),
        max_workers=int(settings.get("max_workers", 1)),
    )
    summary = run_patch_extraction(config)

    result.status = "completed"
    result.detail["summary"] = summary if isinstance(summary, dict) else str(summary)
    return result


def _run_stain(
    paths: StudyPaths,
    recipe: Recipe,
    records: Sequence[SlideRecord],
    *,
    dry_run: bool,
    link_mode: str,
) -> StageResult:
    """Train and apply a stain normalizer over extracted patches."""
    settings = recipe.stage("stain")
    patches_dir = paths.stage_dir("patches", create=False)
    patches_present = patches_dir.is_dir() and any(patches_dir.iterdir())
    output = paths.stage_dir("stain", create=not dry_run)
    result = StageResult(
        stage="stain",
        status="planned",
        output_dir=str(output),
        recipe_hash=recipe.recipe_hash,
        detail={"normalizer": settings.get("normalizer"), "settings": dict(settings)},
    )
    if not dry_run and not patches_present:
        result.status = "failed"
        result.error = (
            "Stain normalization needs extracted patches. Run: rocqipath study run "
            "<name> --stage patches"
        )
        return result
    if dry_run:
        return result

    from rocqipath.stain import (
        StainNormalizationConfig,
        run_stain_normalization_apply,
        run_stain_normalization_train,
    )

    config = StainNormalizationConfig(
        n_type=str(settings.get("normalizer", "macenko")),
        stains=list(settings.get("stains", ["he"])),
        fit_min_tissue=float(settings.get("fit_min_tissue", 0.1)),
        max_train_patches=int(settings.get("max_train_patches", 1000)),
    )
    run_stain_normalization_train(str(patches_dir), str(paths.root), config)
    run_stain_normalization_apply(str(patches_dir), str(paths.root), config)

    result.status = "completed"
    return result


def _run_counts(
    paths: StudyPaths,
    recipe: Recipe,
    records: Sequence[SlideRecord],
    *,
    dry_run: bool,
    link_mode: str,
) -> StageResult:
    """Count chromogen-positive cells, recording per-slide results."""
    settings = recipe.stage("counts")
    wanted = set(settings.get("chromogen_stains") or [])
    slides = [item for item in _usable(records, recipe) if not wanted or item.stain in wanted]
    output = paths.stage_dir("counts", create=not dry_run)
    result = StageResult(
        stage="counts",
        status="planned",
        output_dir=str(output),
        n_items=len(slides),
        recipe_hash=recipe.recipe_hash,
        detail={"stains": sorted(wanted), "settings": dict(settings)},
    )
    if not slides:
        result.status = "skipped"
        result.warnings.append(
            'No chromogen-bearing slides found. Declare chromogen = "dab" under '
            "the relevant [stains.*] tables."
        )
        return result
    if dry_run:
        return result

    from rocqipath.analysis import PositiveCellCounter

    counter = PositiveCellCounter(
        {
            "output_dir": str(paths.root),
            "target_magnification": float(settings["target_magnification"]),
            "patch_size": int(settings["patch_size"]),
            "tissue_threshold": float(settings.get("tissue_threshold", 0.0)),
            "min_cell_area": int(settings.get("min_cell_area", 50)),
        }
    )
    counted = 0
    for record in slides:
        try:
            counter.count_slide(record.path, label=record.stain.upper())
            counted += 1
        except Exception as exc:  # noqa: BLE001 - one slide must not stop the cohort
            result.warnings.append(f"{record.slide_uid}: counting failed ({exc}).")

    result.status = "completed"
    result.n_items = counted
    return result


_RUNNERS: Dict[str, Callable[..., StageResult]] = {
    "tissue": _run_tissue,
    "alignment": _run_alignment,
    "patches": _run_patches,
    "stain": _run_stain,
    "counts": _run_counts,
}


def run_stage(
    stage: str,
    paths: StudyPaths,
    recipe: Recipe,
    records: Sequence[SlideRecord],
    *,
    dry_run: bool = False,
    link_mode: str = "auto",
) -> StageResult:
    """Run one stage against a resolved recipe.

    Parameters
    ----------
    stage : str
        One of :data:`STAGE_ORDER`.
    paths : StudyPaths
        Study layout.
    recipe : Recipe
        Resolved plan.
    records : sequence of SlideRecord
        Indexed slides.
    dry_run : bool, default False
        Resolve inputs and configuration, report the plan, execute nothing.
    link_mode : str, default "auto"
        Staging link strategy.

    Returns
    -------
    StageResult
        What the stage did, or would do.

    Raises
    ------
    ConfigurationError
        If ``stage`` is unknown.
    """
    if stage not in _RUNNERS:
        raise ConfigurationError(
            f"Unknown stage {stage!r}. Known stages: {', '.join(STAGE_ORDER)}."
        )
    settings = recipe.stages.get(stage, {})
    if not settings.get("enabled", True):
        return StageResult(
            stage=stage,
            status="skipped",
            recipe_hash=recipe.recipe_hash,
            warnings=[f"Stage {stage!r} is disabled in recipe.json."],
        )
    try:
        return _RUNNERS[stage](paths, recipe, records, dry_run=dry_run, link_mode=link_mode)
    except ImportError as exc:
        return StageResult(
            stage=stage,
            status="failed",
            recipe_hash=recipe.recipe_hash,
            error=(
                f"Stage {stage!r} needs optional dependencies that are not installed "
                f"({exc}). See docs/start/install.md for the matching extra."
            ),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a result, not a traceback
        return StageResult(
            stage=stage,
            status="failed",
            recipe_hash=recipe.recipe_hash,
            error=f"{type(exc).__name__}: {exc}",
        )


def resolve_stage_order(stages: Optional[Sequence[str]] = None) -> List[str]:
    """Return requested stages in dependency order.

    Parameters
    ----------
    stages : sequence of str, optional
        Requested stages.  Defaults to every stage.

    Returns
    -------
    list of str
        Stages sorted into execution order, duplicates removed.

    Raises
    ------
    ConfigurationError
        If a requested stage is unknown.
    """
    if not stages:
        return list(STAGE_ORDER)
    unknown = sorted({item for item in stages if item not in STAGE_ORDER})
    if unknown:
        raise ConfigurationError(
            f"Unknown stage(s): {', '.join(unknown)}. Known stages: {', '.join(STAGE_ORDER)}."
        )
    return [item for item in STAGE_ORDER if item in set(stages)]


def stage_output_dir(paths: StudyPaths, stage: str) -> Path:
    """Return the output directory for ``stage``."""
    return paths.stage_dir(stage, create=False)
