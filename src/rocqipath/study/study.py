"""The :class:`Study` facade: one object, no path arguments.

Everything below is a thin convenience layer.  Each method resolves inputs
from the study's own index and recipe, then calls the same public pipeline
functions that have always been available — which remain callable directly,
unchanged, for anyone who prefers explicit paths.

Typical session::

    from rocqipath import Study

    study = Study.create("colorectal_cd8", sources=["/mnt/archive/crc_2024"])
    study.index()
    study.survey()
    print(study.verify().format())
    study.plan()
    study.run("alignment")
    study.run("patches")
    study.select("strict", tissue_fraction=0.60)
    print(study.results(selection="strict").format())
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.study.descriptor import (
    StudyDescriptor,
    descriptor_template,
    load_descriptor,
)
from rocqipath.study.index import SlidePair, SlideRecord, build_index, derive_pairs, load_index
from rocqipath.study.index import write_index as _write_index
from rocqipath.study.manifests import manifest_paths, read_manifest
from rocqipath.study.paths import STAGE_DIRECTORIES, StudyPaths
from rocqipath.study.recipe import Recipe, build_recipe, load_recipe
from rocqipath.study.results import ResultTable, aggregate
from rocqipath.study.selection import Selection, build_selection, load_selection
from rocqipath.study.selection import rule_from_thresholds
from rocqipath.study.stages import StageResult, resolve_stage_order, run_stage
from rocqipath.study.survey import StudySurvey, load_survey, run_survey
from rocqipath.study.verify import VerificationReport, verify_study

__all__ = ["Study", "StudyNotFoundError"]


class StudyNotFoundError(ConfigurationError, FileNotFoundError):
    """Raised when a study directory does not exist.

    Inherits :class:`FileNotFoundError` so callers that already handle a
    missing path keep working.
    """


class Study:
    """A cohort of slides plus everything RocqiPath has derived from it.

    Parameters
    ----------
    paths : StudyPaths
        Resolved study layout.
    descriptor : StudyDescriptor, optional
        Pre-parsed descriptor.  Loaded lazily when omitted.
    """

    def __init__(
        self,
        paths: StudyPaths,
        descriptor: Optional[StudyDescriptor] = None,
    ) -> None:
        """Bind a study to its directory."""
        self.paths = paths
        self._descriptor = descriptor
        self._records: Optional[List[SlideRecord]] = None
        self._index_warnings: List[str] = []

    # -- construction -----------------------------------------------------
    @classmethod
    def open(
        cls,
        name: str,
        *,
        home: Optional[Union[str, Path]] = None,
    ) -> "Study":
        """Open an existing study by name.

        Parameters
        ----------
        name : str
            Study name beneath ``$ROCQIPATH_HOME``.
        home : str or pathlib.Path, optional
            Workspace root override.

        Returns
        -------
        Study
            The opened study.

        Raises
        ------
        StudyNotFoundError
            If the study directory does not exist.
        """
        paths = StudyPaths.for_study(name, home)
        if not paths.root.is_dir():
            raise StudyNotFoundError(
                f"No study at {paths.root}. Create one with: "
                f"rocqipath study init {name} --source <slide-dir>"
            )
        return cls(paths)

    @classmethod
    def create(
        cls,
        name: str,
        *,
        sources: Sequence[Union[str, Path]] = (),
        stains: Sequence[str] = ("he", "cd8"),
        home: Optional[Union[str, Path]] = None,
        default_magnification: float = 20.0,
        overwrite: bool = False,
    ) -> "Study":
        """Create a study directory and write a commented ``study.toml``.

        Parameters
        ----------
        name : str
            Study name.
        sources : sequence of str or pathlib.Path
            Slide directories written into the template.
        stains : sequence of str
            Stain keys.  The first is given the ``reference`` role.
        home : str or pathlib.Path, optional
            Workspace root override.
        default_magnification : float, default 20.0
            Physical output magnification.
        overwrite : bool, default False
            Replace an existing descriptor.

        Returns
        -------
        Study
            The new study.

        Raises
        ------
        ConfigurationError
            If a descriptor already exists and ``overwrite`` is ``False``.
        """
        paths = StudyPaths.for_study(name, home).ensure()
        if paths.descriptor.exists() and not overwrite:
            raise ConfigurationError(
                f"{paths.descriptor} already exists. Pass overwrite=True to replace it."
            )
        paths.descriptor.write_text(
            descriptor_template(
                name,
                sources=sources,
                stains=stains,
                default_magnification=default_magnification,
            ),
            encoding="utf-8",
        )
        return cls(paths)

    # -- descriptor and index --------------------------------------------
    @property
    def name(self) -> str:
        """Return the study directory name."""
        return self.paths.name

    @property
    def root(self) -> Path:
        """Return the study root directory."""
        return self.paths.root

    @property
    def descriptor(self) -> StudyDescriptor:
        """Return the parsed ``study.toml``, loading it on first access."""
        if self._descriptor is None:
            self._descriptor = load_descriptor(self.paths.descriptor, name=self.paths.name)
        return self._descriptor

    def reload(self) -> "Study":
        """Discard cached descriptor and index state, then return ``self``."""
        self._descriptor = None
        self._records = None
        self._index_warnings = []
        return self

    def index(self, *, stat_files: bool = True, write: bool = True) -> List[SlideRecord]:
        """Discover every declared slide and write ``index.jsonl``.

        Parameters
        ----------
        stat_files : bool, default True
            Read size, mtime, and a head digest per slide.
        write : bool, default True
            Persist the index.  Disable for a purely in-memory scan.

        Returns
        -------
        list of SlideRecord
            Indexed slides, sorted by case, stain, section.
        """
        records, warnings = build_index(self.descriptor, stat_files=stat_files)
        self._records = records
        self._index_warnings = warnings
        if write:
            self.paths.root.mkdir(parents=True, exist_ok=True)
            _write_index(self.paths.index, records, study=self.descriptor.name)
        return records

    @property
    def index_warnings(self) -> List[str]:
        """Return warnings produced by the most recent indexing pass."""
        return list(self._index_warnings)

    def slides(self, *, refresh: bool = False) -> List[SlideRecord]:
        """Return indexed slides, reading ``index.jsonl`` when needed.

        Parameters
        ----------
        refresh : bool, default False
            Re-scan the sources instead of reading the stored index.

        Returns
        -------
        list of SlideRecord
            Indexed slides.
        """
        if refresh or self._records is None:
            if not refresh and self.paths.index.is_file():
                self._records = load_index(self.paths.index)
            else:
                self.index()
        return list(self._records or [])

    def pairs(self, biomarkers: Optional[Sequence[str]] = None) -> List[SlidePair]:
        """Return derived reference/moving pairs.

        Parameters
        ----------
        biomarkers : sequence of str, optional
            Restrict to these moving stains.

        Returns
        -------
        list of SlidePair
            Pairs derived without duplicating any slide on disk.
        """
        return derive_pairs(self.slides(), biomarkers=biomarkers)

    def cases(self) -> List[str]:
        """Return sorted case identifiers present in the index."""
        return sorted({record.case for record in self.slides()})

    # -- survey, verify, plan --------------------------------------------
    def survey(self, *, write: bool = True, progress: Optional[Any] = None) -> StudySurvey:
        """Measure every indexed slide and write ``survey/``.

        Parameters
        ----------
        write : bool, default True
            Persist the survey.
        progress : callable, optional
            Called with ``(index, total, SlideSurvey)`` after each slide.

        Returns
        -------
        StudySurvey
            Cohort survey.
        """
        result = run_survey(
            self.descriptor.name,
            self.slides(),
            target_magnification=self.descriptor.default_magnification,
            progress=progress,
        )
        if write:
            result.write(self.paths.survey, self.paths.survey_slides)
        return result

    def load_survey(self) -> Optional[StudySurvey]:
        """Return the stored survey, or ``None`` when it has not been run."""
        if not self.paths.survey.is_file():
            return None
        return load_survey(self.paths.survey)

    def verify(self) -> VerificationReport:
        """Check the study for problems that would break a run.

        Returns
        -------
        VerificationReport
            Findings plus a summary of what was inspected.
        """
        return verify_study(
            self.descriptor,
            self.slides(),
            self.load_survey(),
            index_warnings=self.index_warnings,
        )

    def plan(
        self,
        *,
        overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
        write: bool = True,
    ) -> Recipe:
        """Resolve a full plan and write ``recipe.json``.

        Parameters
        ----------
        overrides : Mapping, optional
            Nested ``{stage: {key: value}}`` settings applied last.
        write : bool, default True
            Persist the recipe.

        Returns
        -------
        Recipe
            Resolved, hashed plan.
        """
        recipe = build_recipe(self.descriptor, self.load_survey(), overrides=overrides)
        if write:
            recipe.write(self.paths.recipe)
        return recipe

    def recipe(self) -> Recipe:
        """Return the stored recipe, building one if none exists.

        Returns
        -------
        Recipe
            The plan every stage runs under.
        """
        if self.paths.recipe.is_file():
            return load_recipe(self.paths.recipe)
        return self.plan()

    # -- running ----------------------------------------------------------
    def run(
        self,
        stages: Optional[Union[str, Sequence[str]]] = None,
        *,
        dry_run: bool = False,
        link_mode: str = "auto",
        stop_on_error: bool = True,
    ) -> List[StageResult]:
        """Run one stage, several stages, or the whole pipeline.

        Parameters
        ----------
        stages : str or sequence of str, optional
            Stage names.  Defaults to every stage in dependency order.
        dry_run : bool, default False
            Resolve inputs and configuration and report the plan without
            executing anything.
        link_mode : str, default "auto"
            Staging strategy: ``auto``, ``symlink``, ``hardlink``, or ``copy``.
        stop_on_error : bool, default True
            Stop after the first failing stage.

        Returns
        -------
        list of StageResult
            One result per stage attempted.
        """
        requested = [stages] if isinstance(stages, str) else stages
        order = resolve_stage_order(requested)
        recipe = self.recipe()
        records = self.slides()
        self.paths.ensure()

        results: List[StageResult] = []
        for stage in order:
            result = run_stage(
                stage,
                self.paths,
                recipe,
                records,
                dry_run=dry_run,
                link_mode=link_mode,
            )
            results.append(result)
            if stop_on_error and not result.ok:
                break
        return results

    # -- selections -------------------------------------------------------
    def manifest(self, stage: str, name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Read a stage manifest.

        Parameters
        ----------
        stage : str
            Stage whose manifest to read.
        name : str, optional
            Manifest base name.  Defaults to the stage name.

        Returns
        -------
        list of dict
            Manifest rows.

        Raises
        ------
        ConfigurationError
            If the manifest does not exist.
        """
        rows_path, _ = manifest_paths(self.paths.stage_dir(stage, create=False), name or stage)
        if not rows_path.is_file():
            raise ConfigurationError(
                f"No {stage} manifest at {rows_path}. Run the stage first: "
                f"rocqipath study run {self.name} --stage {stage}"
            )
        return list(read_manifest(rows_path))

    def select(
        self,
        name: str,
        *,
        stage: str = "patches",
        rule: str = "",
        manifest: Optional[str] = None,
        stat_fields: Sequence[str] = ("tissue_fraction", "blur"),
        write: bool = True,
        **thresholds: float,
    ) -> Selection:
        """Create a named QC view over a stage manifest.

        Parameters
        ----------
        name : str
            Selection name.
        stage : str, default "patches"
            Stage whose manifest is filtered.
        rule : str, optional
            Rule expression.  Combined with ``**thresholds`` when both given.
        manifest : str, optional
            Manifest base name.  Defaults to the stage name.
        stat_fields : sequence of str
            Numeric fields summarised over the selected rows.
        write : bool, default True
            Persist the selection under ``selections/``.
        **thresholds : float
            Convenience minimum thresholds, for example ``tissue_fraction=0.6``.

        Returns
        -------
        Selection
            The selection, with the matching artifact identifiers.

        Examples
        --------
        >>> study.select("strict", tissue_fraction=0.6)          # doctest: +SKIP
        >>> study.select("sharp", rule="blur >= percentile('blur', 10)")  # doctest: +SKIP
        """
        expressions = [item for item in (rule.strip(), rule_from_thresholds(**thresholds)) if item]
        combined = " and ".join(expressions)
        records = self.manifest(stage, manifest)
        selection = build_selection(
            name,
            records,
            combined,
            study=self.name,
            stage=stage,
            manifest=str(
                manifest_paths(self.paths.stage_dir(stage, create=False), manifest or stage)[0]
            ),
            recipe_hash=self.recipe().recipe_hash,
            stat_fields=stat_fields,
        )
        if write:
            selection.write(self.paths.selections)
        return selection

    def selection(self, name: str) -> Selection:
        """Load a saved selection by name.

        Parameters
        ----------
        name : str
            Selection name.

        Returns
        -------
        Selection
            The stored selection.

        Raises
        ------
        ConfigurationError
            If no selection of that name exists.
        """
        path = self.paths.selections / f"{name}.json"
        if not path.is_file():
            available = ", ".join(self.selections()) or "none"
            raise ConfigurationError(
                f"No selection named {name!r}. Available selections: {available}."
            )
        return load_selection(path)

    def selections(self) -> List[str]:
        """Return the names of every saved selection."""
        if not self.paths.selections.is_dir():
            return []
        return sorted(path.stem for path in self.paths.selections.glob("*.json"))

    # -- results ----------------------------------------------------------
    def results(
        self,
        *,
        stage: str = "counts",
        manifest: Optional[str] = None,
        selection: Optional[Union[str, Selection]] = None,
        group_by: Sequence[str] = ("case", "stain"),
        sum_fields: Sequence[str] = ("positive_cells", "tissue_area_um2"),
        mean_fields: Sequence[str] = ("tissue_fraction",),
    ) -> ResultTable:
        """Aggregate a stage manifest into a tidy table.

        Parameters
        ----------
        stage : str, default "counts"
            Stage whose manifest to aggregate.
        manifest : str, optional
            Manifest base name.  Defaults to the stage name.
        selection : str or Selection, optional
            Restrict to artifacts in this selection.
        group_by : sequence of str
            Grouping columns.
        sum_fields, mean_fields : sequence of str
            Numeric fields summed or averaged within each group.

        Returns
        -------
        ResultTable
            One row per group.
        """
        chosen = self.selection(selection) if isinstance(selection, str) else selection
        return aggregate(
            self.manifest(stage, manifest),
            group_by=group_by,
            sum_fields=sum_fields,
            mean_fields=mean_fields,
            selection=chosen,
        )

    # -- presentation -----------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        """Return a short overview of the study's current state.

        Returns
        -------
        dict
            Counts and which artifacts exist on disk.
        """
        records = self.slides() if self.paths.index.is_file() else []
        return {
            "name": self.name,
            "root": str(self.root),
            "slides": len(records),
            "cases": len({record.case for record in records}),
            "stains": sorted({record.stain for record in records}),
            "has_survey": self.paths.survey.is_file(),
            "has_recipe": self.paths.recipe.is_file(),
            "selections": self.selections(),
            "stages_present": [
                stage
                for stage in STAGE_DIRECTORIES
                if any(self.paths.stage_dir(stage, create=False).glob("*"))
            ],
        }

    def __repr__(self) -> str:
        """Return a short debugging representation."""
        return f"Study(name={self.name!r}, root={str(self.root)!r})"
