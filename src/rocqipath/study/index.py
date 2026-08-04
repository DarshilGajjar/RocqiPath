"""Build and read the study slide index.

Indexing walks every declared source root once, decodes each filename into
``(case, stain, section)``, and writes one JSON line per physical slide.  From
that point on, no pipeline needs a directory argument: every stage resolves
its inputs from the index.

Identity
--------
Each slide gets a ``slide_uid`` of the form::

    <case>__<stain>__s<NN>

A double underscore separates fields so that case identifiers may themselves
contain single underscores — which hospital accession numbers routinely do.

Pairs are *derived*, never stored.  A pair is a case crossed with its
reference stain and one moving stain, so a single H&E slide can serve every
biomarker in the cohort without being duplicated on disk.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.study.descriptor import (
    MOVING_ROLE,
    REFERENCE_ROLE,
    StudyDescriptor,
    looks_like_slide,
)

__all__ = [
    "SlidePair",
    "SlideRecord",
    "build_index",
    "derive_pairs",
    "group_by_case",
    "load_index",
    "make_slide_uid",
    "write_index",
]

#: Bytes hashed from the head of each slide for a cheap identity fingerprint.
#: Hashing a full 4 GB slide on every index rebuild is not worth the time;
#: head bytes combined with size and mtime detect the changes that matter.
HEAD_HASH_BYTES = 1 << 20


def make_slide_uid(case: str, stain: str, section: Optional[int]) -> str:
    """Compose the canonical slide identifier.

    Parameters
    ----------
    case : str
        Case or block identifier.
    stain : str
        Stain key.
    section : int, optional
        Serial-section number.  Defaults to section 1 when absent.

    Returns
    -------
    str
        ``<case>__<stain>__s<NN>``.
    """
    number = 1 if section is None else int(section)
    return f"{case.strip()}__{stain.strip().lower()}__s{number:02d}"


def _head_digest(path: Path, size_limit: int = HEAD_HASH_BYTES) -> str:
    """Return a short SHA-256 digest of the first bytes of ``path``."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            digest.update(stream.read(size_limit))
    except OSError:
        return ""
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class SlideRecord:
    """One physical slide file and the identity decoded from its name.

    Attributes
    ----------
    slide_uid : str
        Canonical identifier used by every downstream artifact.
    case : str
        Case or block identifier.
    stain : str
        Lowercase stain key.
    section : int
        Serial-section number, defaulting to 1.
    role : {"reference", "moving"}
        Role resolved from the descriptor's stain table.
    path : str
        Absolute path to the slide, in its original location.
    size_bytes : int
        File size at index time.
    mtime : float
        Modification timestamp at index time.
    head_sha256 : str
        Truncated digest of the file's leading bytes.
    source_magnification : float, optional
        Fallback objective magnification from the descriptor, if declared.
    excluded : bool
        Whether a descriptor override drops this slide.
    note : str, optional
        Free text carried from the descriptor override.
    """

    slide_uid: str
    case: str
    stain: str
    section: int
    role: str
    path: str
    size_bytes: int = 0
    mtime: float = 0.0
    head_sha256: str = ""
    source_magnification: Optional[float] = None
    excluded: bool = False
    note: Optional[str] = None

    @property
    def file(self) -> Path:
        """Return the slide path as a :class:`pathlib.Path`."""
        return Path(self.path)

    @property
    def exists(self) -> bool:
        """Return whether the slide file is currently readable."""
        return self.file.is_file()

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this record for ``index.jsonl``."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SlideRecord":
        """Rebuild a record from one ``index.jsonl`` line."""
        known = {key: data[key] for key in data if key in cls.__dataclass_fields__}
        return cls(**known)


@dataclass(frozen=True)
class SlidePair:
    """A reference/moving slide pair derived from the index.

    Attributes
    ----------
    case : str
        Shared case identifier.
    reference : SlideRecord
        Registration target, usually H&E.
    moving : SlideRecord
        Slide warped onto the reference.
    """

    case: str
    reference: SlideRecord
    moving: SlideRecord

    @property
    def pair_uid(self) -> str:
        """Return ``<case>__<reference_stain>-<moving_stain>``."""
        return f"{self.case}__{self.reference.stain}-{self.moving.stain}"

    @property
    def biomarker(self) -> str:
        """Return the moving stain key."""
        return self.moving.stain


def _iter_candidate_files(root: Path, recursive: bool) -> Iterator[Path]:
    """Yield slide-like files beneath ``root``."""
    if not root.is_dir():
        return
    walker: Iterable[Path] = root.rglob("*") if recursive else root.glob("*")
    for candidate in walker:
        if candidate.is_file() and looks_like_slide(candidate):
            yield candidate


def build_index(
    descriptor: StudyDescriptor,
    *,
    stat_files: bool = True,
) -> Tuple[List[SlideRecord], List[str]]:
    """Discover every slide declared by ``descriptor``.

    Parameters
    ----------
    descriptor : StudyDescriptor
        Parsed cohort descriptor.
    stat_files : bool, default True
        Read file size, mtime, and a head digest.  Disable for fast dry runs
        over slow network storage.

    Returns
    -------
    tuple
        ``(records, warnings)``.  Records are sorted by case, stain, section.
        Warnings describe files that were found but could not be indexed.

    Raises
    ------
    ConfigurationError
        If a source pattern is invalid.
    """
    records: Dict[str, SlideRecord] = {}
    warnings: List[str] = []

    for source in descriptor.sources:
        pattern = source.compiled
        root = source.root.expanduser()
        if not root.is_dir():
            warnings.append(f"Source root does not exist: {root}")
            continue
        for path in sorted(_iter_candidate_files(root, source.recursive)):
            match = pattern.search(path.name)
            if match is None:
                warnings.append(f"Filename did not match the source pattern: {path}")
                continue
            groups = match.groupdict()
            case = str(groups.get("case") or "").strip()
            stain = str(groups.get("stain") or "").strip().lower()
            if not case or not stain:
                warnings.append(f"Pattern matched but captured no case/stain: {path}")
                continue
            raw_section = groups.get("section")
            section = int(raw_section) if raw_section else 1
            slide_uid = make_slide_uid(case, stain, section)

            if slide_uid in records:
                warnings.append(
                    f"Duplicate slide_uid {slide_uid!r}: {path} collides with "
                    f"{records[slide_uid].path}. Add a section group to the pattern "
                    "or rename one file."
                )
                continue

            spec = descriptor.stain(stain)
            if spec is None:
                warnings.append(
                    f"Stain {stain!r} is not declared in study.toml (from {path.name}). "
                    f"Add a [stains.{stain}] table to include it."
                )
                role = MOVING_ROLE
                stain_fallback = None
            else:
                role = spec.role
                stain_fallback = spec.source_magnification

            override = descriptor.override(slide_uid)
            stat_size, stat_mtime, digest = 0, 0.0, ""
            if stat_files:
                try:
                    info = path.stat()
                    stat_size, stat_mtime = info.st_size, info.st_mtime
                except OSError as exc:
                    warnings.append(f"Could not stat {path}: {exc}")
                digest = _head_digest(path)

            records[slide_uid] = SlideRecord(
                slide_uid=slide_uid,
                case=case,
                stain=stain,
                section=section,
                role=role,
                path=str(path.resolve()),
                size_bytes=stat_size,
                mtime=stat_mtime,
                head_sha256=digest,
                source_magnification=override.source_magnification or stain_fallback,
                excluded=override.exclude,
                note=override.note,
            )

    ordered = sorted(records.values(), key=lambda item: (item.case, item.stain, item.section))
    return ordered, warnings


def write_index(path: Path, records: Sequence[SlideRecord], *, study: str) -> Path:
    """Write ``index.jsonl`` plus a small sidecar summary.

    Parameters
    ----------
    path : pathlib.Path
        Destination ``index.jsonl``.
    records : sequence of SlideRecord
        Records to write, one per line.
    study : str
        Study name recorded in the sidecar.

    Returns
    -------
    pathlib.Path
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
    sidecar = path.with_suffix(".meta.json")
    stains: Dict[str, int] = {}
    for record in records:
        stains[record.stain] = stains.get(record.stain, 0) + 1
    sidecar.write_text(
        json.dumps(
            {
                "study": study,
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "n_slides": len(records),
                "n_cases": len({record.case for record in records}),
                "slides_per_stain": dict(sorted(stains.items())),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def load_index(path: Path) -> List[SlideRecord]:
    """Read ``index.jsonl`` into records.

    Parameters
    ----------
    path : pathlib.Path
        Index file.

    Returns
    -------
    list of SlideRecord
        Parsed records, excluding blank lines.

    Raises
    ------
    ConfigurationError
        If the index is missing or a line is not valid JSON.
    """
    if not path.is_file():
        raise ConfigurationError(
            f"No slide index at {path}. Build one with: rocqipath study index <name>"
        )
    records: List[SlideRecord] = []
    with open(path, encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                records.append(SlideRecord.from_dict(json.loads(text)))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ConfigurationError(f"{path}: line {number} is not a valid record: {exc}")
    return records


def group_by_case(records: Iterable[SlideRecord]) -> Dict[str, List[SlideRecord]]:
    """Group records by case identifier, preserving stain order.

    Parameters
    ----------
    records : iterable of SlideRecord
        Records to group.

    Returns
    -------
    dict
        Case identifier mapped to its slides.
    """
    grouped: Dict[str, List[SlideRecord]] = {}
    for record in records:
        grouped.setdefault(record.case, []).append(record)
    for slides in grouped.values():
        slides.sort(key=lambda item: (item.stain, item.section))
    return grouped


def derive_pairs(
    records: Iterable[SlideRecord],
    *,
    biomarkers: Optional[Sequence[str]] = None,
    include_excluded: bool = False,
) -> List[SlidePair]:
    """Derive reference/moving pairs without duplicating any slide.

    Parameters
    ----------
    records : iterable of SlideRecord
        Indexed slides.
    biomarkers : sequence of str, optional
        Restrict to these moving stains.  Defaults to every moving stain.
    include_excluded : bool, default False
        Keep slides marked ``excluded`` in the descriptor.

    Returns
    -------
    list of SlidePair
        Pairs sorted by case then moving stain.
    """
    wanted = {item.strip().lower() for item in biomarkers} if biomarkers else None
    pairs: List[SlidePair] = []
    for case, slides in sorted(group_by_case(records).items()):
        usable = [item for item in slides if include_excluded or not item.excluded]
        references = [item for item in usable if item.role == REFERENCE_ROLE]
        if not references:
            continue
        reference = references[0]
        for slide in usable:
            if slide.role != MOVING_ROLE:
                continue
            if wanted is not None and slide.stain not in wanted:
                continue
            pairs.append(SlidePair(case=case, reference=reference, moving=slide))
    return pairs
