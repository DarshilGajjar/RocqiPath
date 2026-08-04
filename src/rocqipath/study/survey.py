"""Survey: measure what the slides actually are, before anything is planned.

The survey is a cheap pass over every indexed slide.  It opens each file,
reads the metadata that governs every later decision — level-0 objective
magnification, microns per pixel, pyramid downsamples, dimensions — and
records the result.  Nothing is resized and no tile is read at full
resolution.

Its purpose is to turn a class of failure that normally appears three hours
into a run ("this slide has no objective metadata", "20x cannot be produced
from a 10x scan") into a pre-flight check that costs seconds.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.study.index import SlideRecord

__all__ = [
    "SlideSurvey",
    "StudySurvey",
    "load_survey",
    "survey_slide",
    "run_survey",
]

_MPP_KEYS = ("openslide.mpp-x", "openslide.mpp-y", "aperio.MPP")
_VENDOR_KEYS = ("openslide.vendor", "tiff.Make")


def _first_property(properties: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
    """Return the first present, non-empty property value among ``keys``."""
    for key in keys:
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _as_float(value: Any) -> Optional[float]:
    """Return ``value`` as a positive float, otherwise ``None``."""
    try:
        parsed = float(str(value).strip().rstrip("xX"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


@dataclass
class SlideSurvey:
    """Measured facts about one slide.

    Attributes
    ----------
    slide_uid, case, stain : str
        Identity carried from the index.
    path : str
        Slide location at survey time.
    readable : bool
        Whether the slide could be opened at all.
    backend : str, optional
        ``"openslide"``, ``"pil"``, or ``None`` when unreadable.
    vendor : str, optional
        Scanner vendor string, when the file records one.
    base_magnification : float, optional
        Resolved level-0 objective magnification.
    magnification_source : str
        Where that value came from: a metadata key, ``"override"``, or
        ``"missing"``.
    mpp : float, optional
        Microns per pixel at level 0.
    level_count : int
        Number of native pyramid levels.
    level_downsamples : list of float
        Native downsample factors.
    width, height : int
        Level-0 dimensions in pixels.
    error : str, optional
        Why the slide could not be surveyed.
    """

    slide_uid: str
    case: str
    stain: str
    path: str
    readable: bool = False
    backend: Optional[str] = None
    vendor: Optional[str] = None
    base_magnification: Optional[float] = None
    magnification_source: str = "missing"
    mpp: Optional[float] = None
    level_count: int = 0
    level_downsamples: List[float] = field(default_factory=list)
    width: int = 0
    height: int = 0
    error: Optional[str] = None

    @property
    def native_magnifications(self) -> List[float]:
        """Return the objective magnification of each native pyramid level."""
        if self.base_magnification is None:
            return []
        return [self.base_magnification / value for value in self.level_downsamples or [1.0]]

    def supports(self, target_magnification: float) -> bool:
        """Return whether ``target_magnification`` can be produced honestly.

        Parameters
        ----------
        target_magnification : float
            Requested physical zoom.

        Returns
        -------
        bool
            ``False`` when the slide is unreadable, has no resolvable
            objective magnification, or was scanned below the request.
        """
        if not self.readable or self.base_magnification is None:
            return False
        return target_magnification <= self.base_magnification + 1e-9

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this survey record."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SlideSurvey":
        """Rebuild a survey record from its serialised form."""
        known = {key: data[key] for key in data if key in cls.__dataclass_fields__}
        return cls(**known)


def survey_slide(record: SlideRecord) -> SlideSurvey:
    """Open one slide and record its measurable properties.

    Parameters
    ----------
    record : SlideRecord
        Indexed slide to inspect.

    Returns
    -------
    SlideSurvey
        Populated survey record.  Failures are captured in ``error`` rather
        than raised, so one unreadable slide never aborts a cohort survey.
    """
    survey = SlideSurvey(
        slide_uid=record.slide_uid,
        case=record.case,
        stain=record.stain,
        path=record.path,
    )
    if not record.exists:
        survey.error = "File not found at the path recorded in the index."
        return survey

    try:
        from rocqipath.core.slide import SlideReader
    except ImportError as exc:  # pragma: no cover - exercised only on base installs
        survey.error = (
            f"Slide backends are not installed ({exc}). "
            'Install them with: python -m pip install -e ".[extraction]"'
        )
        return survey

    reader = None
    try:
        reader = SlideReader(record.path)
        properties = reader.properties
        survey.readable = True
        survey.backend = "openslide" if properties else "pil"
        survey.vendor = _first_property(properties, _VENDOR_KEYS)
        survey.mpp = _as_float(_first_property(properties, _MPP_KEYS))
        survey.level_downsamples = [float(value) for value in reader.level_downsamples]
        survey.level_count = len(survey.level_downsamples)
        survey.width, survey.height = (int(value) for value in reader.dimensions)

        from rocqipath.core.magnification import objective_magnification_from_properties

        try:
            base, source = objective_magnification_from_properties(
                properties, fallback=record.source_magnification
            )
            survey.base_magnification = base
            survey.magnification_source = "override" if source == "fallback" else source
        except ValueError:
            survey.magnification_source = "missing"
    except Exception as exc:  # noqa: BLE001 - one bad slide must not stop the survey
        survey.error = f"{type(exc).__name__}: {exc}"
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception:  # noqa: BLE001 - close failures are not interesting here
                pass
    return survey


@dataclass
class StudySurvey:
    """Cohort-level survey summary plus every per-slide record.

    Attributes
    ----------
    study : str
        Study name.
    generated_at : str
        UTC timestamp.
    target_magnification : float
        Magnification the cohort was checked against.
    slides : list of SlideSurvey
        One record per indexed slide.
    """

    study: str
    generated_at: str
    target_magnification: float
    slides: List[SlideSurvey] = field(default_factory=list)

    def by_uid(self) -> Dict[str, SlideSurvey]:
        """Return the per-slide records keyed by ``slide_uid``."""
        return {item.slide_uid: item for item in self.slides}

    @property
    def unreadable(self) -> List[SlideSurvey]:
        """Return slides that could not be opened."""
        return [item for item in self.slides if not item.readable]

    @property
    def missing_magnification(self) -> List[SlideSurvey]:
        """Return readable slides with no resolvable objective magnification."""
        return [
            item for item in self.slides if item.readable and item.magnification_source == "missing"
        ]

    def below_target(self, target_magnification: Optional[float] = None) -> List[SlideSurvey]:
        """Return slides scanned below the requested magnification.

        Parameters
        ----------
        target_magnification : float, optional
            Overrides the magnification recorded on the survey.

        Returns
        -------
        list of SlideSurvey
            Slides that cannot honestly produce the requested zoom.
        """
        target = target_magnification or self.target_magnification
        return [
            item
            for item in self.slides
            if item.readable and item.base_magnification is not None and not item.supports(target)
        ]

    def magnification_histogram(self) -> Dict[str, int]:
        """Return a count of slides per level-0 objective magnification."""
        histogram: Dict[str, int] = {}
        for item in self.slides:
            key = "unknown" if item.base_magnification is None else f"{item.base_magnification:g}x"
            histogram[key] = histogram.get(key, 0) + 1
        return dict(sorted(histogram.items()))

    def summary(self) -> Dict[str, Any]:
        """Return the cohort-level block written to ``survey.json``."""
        return {
            "study": self.study,
            "generated_at": self.generated_at,
            "target_magnification": self.target_magnification,
            "n_slides": len(self.slides),
            "n_readable": sum(1 for item in self.slides if item.readable),
            "n_unreadable": len(self.unreadable),
            "n_missing_magnification": len(self.missing_magnification),
            "n_below_target": len(self.below_target()),
            "magnification_histogram": self.magnification_histogram(),
            "cases": sorted({item.case for item in self.slides}),
            "stains": sorted({item.stain for item in self.slides}),
        }

    def write(self, survey_path: Path, slides_dir: Path) -> Path:
        """Write the cohort summary and one JSON file per slide.

        Parameters
        ----------
        survey_path : pathlib.Path
            Destination ``survey.json``.
        slides_dir : pathlib.Path
            Directory receiving per-slide records.

        Returns
        -------
        pathlib.Path
            The summary path written.
        """
        survey_path.parent.mkdir(parents=True, exist_ok=True)
        slides_dir.mkdir(parents=True, exist_ok=True)
        payload = self.summary()
        payload["slides"] = [item.to_dict() for item in self.slides]
        survey_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        for item in self.slides:
            target = slides_dir / f"{item.slide_uid}.json"
            target.write_text(json.dumps(item.to_dict(), indent=2) + "\n", encoding="utf-8")
        return survey_path


def run_survey(
    study: str,
    records: Sequence[SlideRecord],
    *,
    target_magnification: float,
    progress: Optional[Any] = None,
) -> StudySurvey:
    """Survey every indexed slide.

    Parameters
    ----------
    study : str
        Study name recorded in the output.
    records : sequence of SlideRecord
        Slides to inspect.
    target_magnification : float
        Magnification the cohort is checked against.
    progress : callable, optional
        Called with ``(index, total, SlideSurvey)`` after each slide.

    Returns
    -------
    StudySurvey
        Cohort survey, ready to write.
    """
    results: List[SlideSurvey] = []
    total = len(records)
    for position, record in enumerate(records, start=1):
        result = survey_slide(record)
        results.append(result)
        if progress is not None:
            progress(position, total, result)
    return StudySurvey(
        study=study,
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        target_magnification=float(target_magnification),
        slides=results,
    )


def load_survey(path: Path) -> StudySurvey:
    """Read a previously written ``survey.json``.

    Parameters
    ----------
    path : pathlib.Path
        Survey summary path.

    Returns
    -------
    StudySurvey
        Parsed survey.

    Raises
    ------
    ConfigurationError
        If the file is missing or malformed.
    """
    if not path.is_file():
        raise ConfigurationError(f"No survey at {path}. Run it with: rocqipath study survey <name>")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{path} is not valid JSON: {exc}") from exc
    return StudySurvey(
        study=str(payload.get("study", "")),
        generated_at=str(payload.get("generated_at", "")),
        target_magnification=float(payload.get("target_magnification", 0.0)),
        slides=[SlideSurvey.from_dict(item) for item in payload.get("slides", [])],
    )
