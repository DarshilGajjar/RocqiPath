"""The recipe: a resolved, hashed plan that separates deciding from doing.

``recipe.json`` is the single most useful artifact in a study.  It holds the
fully resolved settings for every stage — no ``None``, no "auto", nothing left
for a pipeline to guess at run time — derived from the descriptor you wrote and
the survey RocqiPath measured.

Because it is an ordinary file you can read, edit, diff, and commit:

* a reviewer can see exactly what was run without reading any Python;
* changing one number and re-running is a two-line diff, not a code change;
* every artifact records the recipe hash it was produced under, so a stage
  can tell whether existing output is still current and skip it if so.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.study.descriptor import StudyDescriptor
from rocqipath.study.survey import StudySurvey

__all__ = [
    "RECIPE_SCHEMA_VERSION",
    "Recipe",
    "build_recipe",
    "compute_recipe_hash",
    "load_recipe",
]

#: Bumped whenever the recipe layout changes in a way that invalidates
#: previously written stage output.
RECIPE_SCHEMA_VERSION = 1


def compute_recipe_hash(payload: Mapping[str, Any]) -> str:
    """Hash the decision-bearing parts of a recipe.

    Parameters
    ----------
    payload : Mapping
        Recipe body.  Bookkeeping keys (``generated_at``, ``recipe_hash``,
        ``rocqipath_version``) are excluded so that regenerating an unchanged
        recipe produces an unchanged hash.

    Returns
    -------
    str
        Twelve hex characters — short enough to read in a filename, long
        enough to distinguish plans in practice.
    """
    ignored = {"generated_at", "recipe_hash", "rocqipath_version"}
    material = {key: value for key, value in payload.items() if key not in ignored}
    encoded = json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


@dataclass
class Recipe:
    """A resolved plan for one study.

    Attributes
    ----------
    study : str
        Study name.
    schema_version : int
        Recipe layout version.
    generated_at : str
        UTC timestamp of generation.
    rocqipath_version : str
        Package version that produced the plan.
    recipe_hash : str
        Digest of the decision-bearing content.
    stages : dict
        Per-stage resolved settings.
    slides : dict
        Per-slide resolved settings, chiefly magnification handling.
    notes : list of str
        Decisions worth surfacing, for example slides dropped from a stage.
    """

    study: str
    schema_version: int = RECIPE_SCHEMA_VERSION
    generated_at: str = ""
    rocqipath_version: str = ""
    recipe_hash: str = ""
    stages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    slides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def stage(self, name: str) -> Dict[str, Any]:
        """Return resolved settings for one stage.

        Parameters
        ----------
        name : str
            Stage name.

        Returns
        -------
        dict
            Resolved settings.

        Raises
        ------
        ConfigurationError
            If the stage is absent from the recipe.
        """
        if name not in self.stages:
            known = ", ".join(sorted(self.stages)) or "none"
            raise ConfigurationError(
                f"Stage {name!r} is not in this recipe. Available stages: {known}."
            )
        return self.stages[name]

    def slide_source_magnification(self, slide_uid: str) -> Optional[float]:
        """Return the resolved fallback magnification for one slide."""
        entry = self.slides.get(slide_uid) or {}
        value = entry.get("source_magnification")
        return None if value is None else float(value)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the recipe for ``recipe.json``."""
        return {
            "study": self.study,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "rocqipath_version": self.rocqipath_version,
            "recipe_hash": self.recipe_hash,
            "stages": self.stages,
            "slides": self.slides,
            "notes": self.notes,
        }

    def write(self, path: Path) -> Path:
        """Write the recipe to ``path`` and return it."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Recipe":
        """Rebuild a recipe from its serialised form."""
        return cls(
            study=str(data.get("study", "")),
            schema_version=int(data.get("schema_version", RECIPE_SCHEMA_VERSION)),
            generated_at=str(data.get("generated_at", "")),
            rocqipath_version=str(data.get("rocqipath_version", "")),
            recipe_hash=str(data.get("recipe_hash", "")),
            stages=dict(data.get("stages", {})),
            slides=dict(data.get("slides", {})),
            notes=list(data.get("notes", [])),
        )


def build_recipe(
    descriptor: StudyDescriptor,
    survey: Optional[StudySurvey] = None,
    *,
    overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Recipe:
    """Resolve a full plan from the descriptor and, when available, the survey.

    Parameters
    ----------
    descriptor : StudyDescriptor
        Cohort facts declared by the user.
    survey : StudySurvey, optional
        Measured slide facts.  When omitted the plan is still produced, but
        per-slide magnification handling cannot be checked.
    overrides : Mapping, optional
        Nested ``{stage: {key: value}}`` overrides applied last, so a caller
        can pin one setting without hand-editing the file.

    Returns
    -------
    Recipe
        Resolved, hashed plan.
    """
    from rocqipath import __version__

    target = float(descriptor.default_magnification)
    detection = float(descriptor.detection_magnification)
    stride = int(descriptor.stride or descriptor.patch_size)
    reference = (descriptor.reference_stains or ["he"])[0]
    moving = sorted(descriptor.moving_stains)
    notes: List[str] = []

    stages: Dict[str, Dict[str, Any]] = {
        "tissue": {
            "enabled": True,
            "target_magnification": target,
            "detection_magnification": detection,
            "min_area_fraction": 0.005,
            "preview_scale": 0.2,
            "tif_compression": "lzw",
            "tif_quality": 99,
            "skip_existing": True,
            "mode": "wsi",
        },
        "alignment": {
            "enabled": bool(moving),
            "method": descriptor.alignment_method,
            "target_magnification": target,
            "reference_stain": reference,
            "moving_stains": moving,
            "patch_size": 1024,
            "grid_density": 1,
            "qc_enabled": True,
            "keep_diagnostics": True,
        },
        "patches": {
            "enabled": bool(moving),
            "target_magnification": target,
            "patch_size": int(descriptor.patch_size),
            "stride": stride,
            "reference_stain": reference,
            "moving_stains": moving,
            "dimension_tolerance": 0.01,
            "max_workers": 1,
            # Measure-everything: extraction writes every tile and records
            # its properties. Filtering happens in a selection, not here.
            "tissue_threshold": 0.0,
        },
        "stain": {
            "enabled": True,
            "normalizer": descriptor.normalizer,
            "stains": [reference] + moving,
            "fit_min_tissue": 0.1,
            "max_train_patches": 1000,
        },
        "counts": {
            "enabled": bool(moving),
            "target_magnification": target,
            "patch_size": int(descriptor.patch_size),
            "min_cell_area": 50,
            "max_cell_area": None,
            "chromogen_stains": sorted(
                key
                for key, spec in descriptor.stains.items()
                if (spec.chromogen or "").lower() == "dab"
            ),
            # As above: counts are stored per patch and aggregated through a
            # selection, so QC thresholds never require a re-count.
            "tissue_threshold": 0.0,
        },
        "selection": {
            "default": "all",
            "suggested_rule": "tissue_fraction >= 0.5",
        },
    }

    slides: Dict[str, Dict[str, Any]] = {}
    if survey is not None:
        for item in survey.slides:
            entry: Dict[str, Any] = {
                "case": item.case,
                "stain": item.stain,
                "base_magnification": item.base_magnification,
                "magnification_source": item.magnification_source,
                "source_magnification": (
                    item.base_magnification if item.magnification_source == "override" else None
                ),
                "usable": item.supports(target),
            }
            if not item.readable:
                entry["usable"] = False
                notes.append(f"{item.slide_uid}: unreadable ({item.error or 'unknown error'}).")
            elif item.magnification_source == "missing":
                notes.append(
                    f"{item.slide_uid}: no objective metadata. Set source_magnification "
                    f'under [overrides."{item.slide_uid}"] in study.toml.'
                )
            elif not item.supports(target):
                notes.append(
                    f"{item.slide_uid}: scanned at {item.base_magnification:g}x, below the "
                    f"requested {target:g}x. RocqiPath will not invent resolution."
                )
            slides[item.slide_uid] = entry

    if overrides:
        for stage_name, values in overrides.items():
            if stage_name not in stages:
                raise ConfigurationError(
                    f"Cannot override unknown stage {stage_name!r}. "
                    f"Known stages: {', '.join(sorted(stages))}."
                )
            stages[stage_name].update(dict(values))
        notes.append("Caller-supplied overrides were applied to this recipe.")

    recipe = Recipe(
        study=descriptor.name,
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        rocqipath_version=__version__,
        stages=stages,
        slides=slides,
        notes=notes,
    )
    recipe.recipe_hash = compute_recipe_hash(recipe.to_dict())
    return recipe


def load_recipe(path: Path) -> Recipe:
    """Read ``recipe.json``.

    Parameters
    ----------
    path : pathlib.Path
        Recipe path.

    Returns
    -------
    Recipe
        Parsed plan.

    Raises
    ------
    ConfigurationError
        If the file is missing or malformed.
    """
    if not path.is_file():
        raise ConfigurationError(
            f"No recipe at {path}. Build one with: rocqipath study plan <name>"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{path} is not valid JSON: {exc}") from exc
    return Recipe.from_dict(payload)
