"""Pre-flight verification: fail in seconds, not three hours in.

``verify`` is the cheapest useful command in RocqiPath.  It reads the
descriptor, the index, and the survey, and reports every problem that would
otherwise surface part-way through an overnight run: missing files, cases with
no reference stain, slides scanned below the requested magnification, stains
that were found on disk but never declared.

Each issue carries a severity and, wherever possible, the exact edit that
resolves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from rocqipath.study.descriptor import MOVING_ROLE, REFERENCE_ROLE, StudyDescriptor
from rocqipath.study.index import SlideRecord, group_by_case
from rocqipath.study.survey import StudySurvey

__all__ = ["Issue", "VerificationReport", "verify_study"]

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    """One verification finding.

    Attributes
    ----------
    severity : {"error", "warning"}
        Errors block a run; warnings do not.
    scope : str
        Where the problem lives: ``descriptor``, ``index``, ``survey``, or a
        ``slide_uid``.
    message : str
        What is wrong.
    fix : str, optional
        The concrete edit or command that resolves it.
    """

    severity: str
    scope: str
    message: str
    fix: Optional[str] = None

    def format(self) -> str:
        """Return a single-line, human-readable rendering of this issue."""
        label = "ERROR  " if self.severity == ERROR else "warning"
        text = f"{label}  [{self.scope}] {self.message}"
        return f"{text}\n           fix: {self.fix}" if self.fix else text


@dataclass
class VerificationReport:
    """The outcome of verifying one study.

    Attributes
    ----------
    study : str
        Study name.
    issues : list of Issue
        Every finding, errors first.
    checked : dict
        Counts of what was inspected.
    """

    study: str
    issues: List[Issue]
    checked: Dict[str, int]

    @property
    def errors(self) -> List[Issue]:
        """Return blocking issues."""
        return [item for item in self.issues if item.severity == ERROR]

    @property
    def warnings(self) -> List[Issue]:
        """Return non-blocking issues."""
        return [item for item in self.issues if item.severity == WARNING]

    @property
    def ok(self) -> bool:
        """Return whether the study is safe to run."""
        return not self.errors

    def format(self) -> str:
        """Return a printable multi-line report."""
        lines = [f"Study: {self.study}"]
        for key, value in sorted(self.checked.items()):
            lines.append(f"  {key.replace('_', ' ')}: {value}")
        if not self.issues:
            lines.append("\nNo problems found. This study is ready to run.")
            return "\n".join(lines)
        lines.append("")
        for issue in self.issues:
            lines.append(issue.format())
        lines.append("")
        lines.append(f"{len(self.errors)} error(s), {len(self.warnings)} warning(s).")
        return "\n".join(lines)


def verify_study(
    descriptor: StudyDescriptor,
    records: Sequence[SlideRecord] = (),
    survey: Optional[StudySurvey] = None,
    *,
    index_warnings: Sequence[str] = (),
) -> VerificationReport:
    """Check a study for problems that would break a run.

    Parameters
    ----------
    descriptor : StudyDescriptor
        Parsed cohort descriptor.
    records : sequence of SlideRecord, optional
        Indexed slides.  An empty index is itself reported.
    survey : StudySurvey, optional
        Measured slide facts.  Magnification checks are skipped without it.
    index_warnings : sequence of str, optional
        Warnings carried over from indexing, for example unmatched filenames.

    Returns
    -------
    VerificationReport
        All findings plus what was inspected.
    """
    issues: List[Issue] = []

    for problem in descriptor.validate():
        issues.append(Issue(ERROR, "descriptor", problem, "Edit study.toml and re-run verify."))

    for warning in index_warnings:
        issues.append(Issue(WARNING, "index", warning))

    if not records:
        issues.append(
            Issue(
                ERROR,
                "index",
                "No slides were indexed.",
                "Check the [[sources]] root and pattern, then run: rocqipath study index <name>",
            )
        )

    active = [item for item in records if not item.excluded]
    for record in active:
        if not record.exists:
            issues.append(
                Issue(
                    ERROR,
                    record.slide_uid,
                    f"Indexed file is no longer readable: {record.path}",
                    "Re-run: rocqipath study index <name>",
                )
            )

    declared = set(descriptor.stains)
    found = {record.stain for record in active}
    for stain in sorted(found - declared):
        issues.append(
            Issue(
                WARNING,
                "descriptor",
                f"Stain {stain!r} appears on disk but is not declared.",
                f"Add a [stains.{stain}] table to study.toml, or narrow the source pattern.",
            )
        )
    for stain in sorted(declared - found):
        issues.append(
            Issue(
                WARNING,
                "descriptor",
                f"Stain {stain!r} is declared but no slide matched it.",
                "Check the filename pattern, or remove the stain from study.toml.",
            )
        )

    for case, slides in sorted(group_by_case(active).items()):
        roles = {item.role for item in slides}
        if REFERENCE_ROLE not in roles:
            issues.append(
                Issue(
                    ERROR,
                    case,
                    "Case has no reference slide, so no pair can be derived.",
                    "Add the reference slide, or exclude the case under [overrides].",
                )
            )
        if MOVING_ROLE not in roles:
            issues.append(
                Issue(
                    WARNING,
                    case,
                    "Case has a reference slide but no moving slide.",
                    "Alignment, patch extraction, and counting will skip this case.",
                )
            )

    if survey is not None:
        target = descriptor.default_magnification
        by_uid = survey.by_uid()
        for record in active:
            entry = by_uid.get(record.slide_uid)
            if entry is None:
                issues.append(
                    Issue(
                        WARNING,
                        record.slide_uid,
                        "Slide is indexed but absent from the survey.",
                        "Re-run: rocqipath study survey <name>",
                    )
                )
                continue
            if not entry.readable:
                issues.append(
                    Issue(
                        ERROR,
                        record.slide_uid,
                        f"Slide could not be opened: {entry.error or 'unknown error'}",
                        "Confirm the native OpenSlide/libvips runtimes are installed.",
                    )
                )
                continue
            if entry.magnification_source == "missing":
                issues.append(
                    Issue(
                        ERROR,
                        record.slide_uid,
                        "Slide records no objective magnification.",
                        f'Add [overrides."{record.slide_uid}"] with source_magnification '
                        "to study.toml.",
                    )
                )
                continue
            if not entry.supports(target):
                issues.append(
                    Issue(
                        ERROR,
                        record.slide_uid,
                        f"Scanned at {entry.base_magnification:g}x, below the requested "
                        f"{target:g}x.",
                        "Lower default_magnification, or exclude this slide under [overrides].",
                    )
                )

    issues.sort(key=lambda item: (item.severity != ERROR, item.scope))
    return VerificationReport(
        study=descriptor.name,
        issues=issues,
        checked={
            "slides_indexed": len(records),
            "slides_active": len(active),
            "cases": len(group_by_case(active)),
            "stains_declared": len(declared),
            "slides_surveyed": 0 if survey is None else len(survey.slides),
        },
    )
