"""Study workspace: descriptor, index, survey, recipe, manifests, selections.

RocqiPath organises work into *studies*.  A study is one cohort of slides plus
everything derived from it, and it follows a single flow::

    study.toml  ->  survey  ->  recipe  ->  stage output + manifests  ->  selections
    (you write)     (measured)  (decided)   (pixels + measurements)     (QC views)

Two ideas do most of the work.

The **recipe** is a resolved, hashed plan written to disk.  Deciding what to do
is separated from doing it, so a plan can be read, edited, diffed, and
committed without touching any Python.

**Manifests** record measurements and never decisions.  A stage writes every
artifact it produced along with the properties a QC rule might care about, and
filtering happens afterwards in a **selection** — which means changing a
threshold costs seconds instead of re-running an overnight job.

Slides are referenced, never ingested.  Whole-slide images are large and often
live on read-only storage, so a study points at them where they already are.
"""

from __future__ import annotations

from rocqipath.study.descriptor import (
    DescriptorNotFoundError,
    SlideOverride,
    SourceSpec,
    StainSpec,
    StudyDescriptor,
    descriptor_template,
    load_descriptor,
)
from rocqipath.study.doctor import Diagnostics, collect_diagnostics, format_diagnostics
from rocqipath.study.index import (
    SlidePair,
    SlideRecord,
    build_index,
    derive_pairs,
    load_index,
    make_slide_uid,
    write_index,
)
from rocqipath.study.manifests import (
    ManifestInfo,
    ManifestWriter,
    read_manifest,
    read_manifest_info,
    summarise_field,
)
from rocqipath.study.paths import HOME_ENV_VAR, STAGE_DIRECTORIES, StudyPaths, resolve_home
from rocqipath.study.recipe import Recipe, build_recipe, compute_recipe_hash, load_recipe
from rocqipath.study.results import ResultTable, aggregate, write_csv
from rocqipath.study.selection import (
    RuleError,
    Selection,
    build_selection,
    evaluate_rule,
    load_selection,
)
from rocqipath.study.stages import STAGE_ORDER, StageResult, run_stage
from rocqipath.study.study import Study, StudyNotFoundError
from rocqipath.study.survey import SlideSurvey, StudySurvey, load_survey, run_survey
from rocqipath.study.verify import Issue, VerificationReport, verify_study

__all__ = [
    "HOME_ENV_VAR",
    "STAGE_DIRECTORIES",
    "STAGE_ORDER",
    "DescriptorNotFoundError",
    "Diagnostics",
    "Issue",
    "ManifestInfo",
    "ManifestWriter",
    "Recipe",
    "ResultTable",
    "RuleError",
    "Selection",
    "SlideOverride",
    "SlidePair",
    "SlideRecord",
    "SlideSurvey",
    "SourceSpec",
    "StageResult",
    "StainSpec",
    "Study",
    "StudyDescriptor",
    "StudyNotFoundError",
    "StudyPaths",
    "StudySurvey",
    "VerificationReport",
    "aggregate",
    "build_index",
    "build_recipe",
    "build_selection",
    "collect_diagnostics",
    "compute_recipe_hash",
    "derive_pairs",
    "descriptor_template",
    "evaluate_rule",
    "format_diagnostics",
    "load_descriptor",
    "load_index",
    "load_recipe",
    "load_selection",
    "load_survey",
    "make_slide_uid",
    "read_manifest",
    "read_manifest_info",
    "resolve_home",
    "run_stage",
    "run_survey",
    "summarise_field",
    "verify_study",
    "write_csv",
    "write_index",
]
