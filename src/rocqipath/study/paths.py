"""Resolve ``ROCQIPATH_HOME`` and the on-disk layout of a single study.

RocqiPath writes everything it produces beneath one root directory.  Slides
themselves are *referenced*, never ingested: whole-slide images are large and
frequently live on read-only network storage, so copying a cohort into a
managed "raw" directory is not practical.

Layout
------
::

    $ROCQIPATH_HOME/
    └── <study_name>/
        ├── study.toml          human-authored cohort descriptor
        ├── index.jsonl         generated: one line per physical slide
        ├── survey/             generated: measured slide facts
        ├── recipe.json         generated: resolved, hashed plan
        ├── alignment/          stage outputs (existing module names)
        ├── tissue/
        ├── patches/
        ├── stain/
        ├── counts/
        ├── selections/         named QC views over stage manifests
        ├── qc/
        ├── logs/
        └── _staging/           internal link farm for directory-based stages
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.core.output import safe_name

__all__ = [
    "HOME_ENV_VAR",
    "STAGE_DIRECTORIES",
    "StudyPaths",
    "default_home",
    "resolve_home",
]

HOME_ENV_VAR = "ROCQIPATH_HOME"

#: Stage directory names, in pipeline order.  These deliberately match the
#: existing ``<root>/<module>/<item>`` module names so that studies and
#: hand-run pipelines produce interchangeable trees.
STAGE_DIRECTORIES = (
    "alignment",
    "tissue",
    "patches",
    "stain",
    "counts",
)


def default_home() -> Path:
    """Return the fallback workspace root used when the env var is unset.

    Returns
    -------
    pathlib.Path
        ``~/rocqipath`` expanded to an absolute path.
    """
    return Path.home() / "rocqipath"


def resolve_home(home: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the workspace root from an argument, the environment, or default.

    Parameters
    ----------
    home : str or pathlib.Path, optional
        Explicit root.  Takes precedence over the environment variable.

    Returns
    -------
    pathlib.Path
        Absolute workspace root.  The directory is not created here.
    """
    if home is not None:
        return Path(home).expanduser().resolve()
    from_env = os.environ.get(HOME_ENV_VAR, "").strip()
    if from_env:
        return Path(from_env).expanduser().resolve()
    return default_home().resolve()


@dataclass(frozen=True)
class StudyPaths:
    """Every path belonging to one study, derived from its root directory.

    Attributes
    ----------
    root : pathlib.Path
        ``$ROCQIPATH_HOME/<study_name>``.
    """

    root: Path

    @classmethod
    def for_study(
        cls,
        name: str,
        home: Optional[Union[str, Path]] = None,
    ) -> "StudyPaths":
        """Build the layout for ``name`` beneath the resolved workspace root.

        Parameters
        ----------
        name : str
            Study name.  Sanitised the same way as every other RocqiPath
            output directory component.
        home : str or pathlib.Path, optional
            Workspace root override.

        Returns
        -------
        StudyPaths
            Path bundle for the study.

        Raises
        ------
        ConfigurationError
            If ``name`` is empty or sanitises to an empty string.
        """
        try:
            cleaned = safe_name(name)
        except ValueError as exc:
            raise ConfigurationError(f"Invalid study name {name!r}: {exc}") from exc
        return cls(root=resolve_home(home) / cleaned)

    @property
    def name(self) -> str:
        """Return the study's directory name."""
        return self.root.name

    @property
    def descriptor(self) -> Path:
        """Return the path to ``study.toml``."""
        return self.root / "study.toml"

    @property
    def index(self) -> Path:
        """Return the path to the generated slide index."""
        return self.root / "index.jsonl"

    @property
    def survey_dir(self) -> Path:
        """Return the survey directory."""
        return self.root / "survey"

    @property
    def survey(self) -> Path:
        """Return the cohort-level survey summary."""
        return self.survey_dir / "survey.json"

    @property
    def survey_slides(self) -> Path:
        """Return the per-slide survey directory."""
        return self.survey_dir / "slides"

    @property
    def recipe(self) -> Path:
        """Return the resolved plan file."""
        return self.root / "recipe.json"

    @property
    def selections(self) -> Path:
        """Return the directory holding named selections."""
        return self.root / "selections"

    @property
    def qc(self) -> Path:
        """Return the quality-control output directory."""
        return self.root / "qc"

    @property
    def logs(self) -> Path:
        """Return the log directory."""
        return self.root / "logs"

    @property
    def staging(self) -> Path:
        """Return the internal staging (link farm) directory."""
        return self.root / "_staging"

    def stage_dir(self, stage: str, *, create: bool = False) -> Path:
        """Return ``<root>/<stage>`` for a known stage name.

        Parameters
        ----------
        stage : str
            One of :data:`STAGE_DIRECTORIES`.
        create : bool, default False
            Create the directory when missing.

        Returns
        -------
        pathlib.Path
            The stage output directory.

        Raises
        ------
        ConfigurationError
            If ``stage`` is not a recognised stage name.
        """
        if stage not in STAGE_DIRECTORIES:
            known = ", ".join(STAGE_DIRECTORIES)
            raise ConfigurationError(f"Unknown stage {stage!r}. Known stages: {known}.")
        path = self.root / stage
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure(self) -> "StudyPaths":
        """Create the standard directory skeleton and return ``self``.

        Returns
        -------
        StudyPaths
            This instance, for chaining.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        for path in (self.survey_slides, self.selections, self.qc, self.logs):
            path.mkdir(parents=True, exist_ok=True)
        for stage in STAGE_DIRECTORIES:
            self.stage_dir(stage, create=True)
        return self
