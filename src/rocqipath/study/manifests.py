"""Artifact manifests: the substrate every selection is computed over.

A manifest records *measurements*, never decisions.  When patch extraction
runs, it writes every tile it produced along with the properties that a QC
rule might later care about — tissue fraction, blur, optical density — and
applies no threshold of its own.

That separation is what makes changing your mind cheap.  Tightening a tissue
threshold from 0.50 to 0.60 becomes a rule evaluated over an existing manifest
in seconds, instead of a re-extraction measured in hours.

Format
------
Two files per manifest:

``<name>.jsonl``
    One JSON object per artifact.  JSONL because patch-level manifests reach
    millions of rows, and a single JSON array cannot be streamed or appended.

``<name>.manifest.json``
    The sidecar: stage, recipe hash, package version, row count, and the field
    names present in the rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Type

from rocqipath.core.exceptions import ConfigurationError

__all__ = [
    "ManifestInfo",
    "ManifestWriter",
    "manifest_paths",
    "read_manifest",
    "read_manifest_info",
    "summarise_field",
]


def manifest_paths(directory: Path, name: str) -> tuple[Path, Path]:
    """Return the ``(rows, sidecar)`` paths for a manifest.

    Parameters
    ----------
    directory : pathlib.Path
        Directory holding the manifest.
    name : str
        Manifest base name, for example ``"patches"``.

    Returns
    -------
    tuple of pathlib.Path
        ``(<dir>/<name>.jsonl, <dir>/<name>.manifest.json)``.
    """
    return directory / f"{name}.jsonl", directory / f"{name}.manifest.json"


@dataclass
class ManifestInfo:
    """Sidecar metadata describing one manifest.

    Attributes
    ----------
    stage : str
        Stage that produced the rows.
    study : str
        Study name.
    recipe_hash : str
        Recipe the rows were produced under.
    rocqipath_version : str
        Package version at write time.
    generated_at : str
        UTC timestamp.
    n_rows : int
        Number of records written.
    fields : list of str
        Field names observed across the rows.
    extra : dict
        Free-form stage-specific metadata.
    """

    stage: str
    study: str = ""
    recipe_hash: str = ""
    rocqipath_version: str = ""
    generated_at: str = ""
    n_rows: int = 0
    fields: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this sidecar."""
        return {
            "stage": self.stage,
            "study": self.study,
            "recipe_hash": self.recipe_hash,
            "rocqipath_version": self.rocqipath_version,
            "generated_at": self.generated_at,
            "n_rows": self.n_rows,
            "fields": self.fields,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ManifestInfo":
        """Rebuild a sidecar from its serialised form."""
        return cls(
            stage=str(data.get("stage", "")),
            study=str(data.get("study", "")),
            recipe_hash=str(data.get("recipe_hash", "")),
            rocqipath_version=str(data.get("rocqipath_version", "")),
            generated_at=str(data.get("generated_at", "")),
            n_rows=int(data.get("n_rows", 0)),
            fields=list(data.get("fields", [])),
            extra=dict(data.get("extra", {})),
        )


class ManifestWriter:
    """Append artifact records to a JSONL manifest and write its sidecar.

    Use as a context manager so the sidecar is written even when the stage
    raises part-way through::

        with ManifestWriter(directory, "patches", stage="patches") as writer:
            for tile in tiles:
                writer.write(tile_record)

    Parameters
    ----------
    directory : pathlib.Path
        Destination directory, created if missing.
    name : str
        Manifest base name.
    stage : str
        Stage identifier recorded in the sidecar.
    study : str, optional
        Study name.
    recipe_hash : str, optional
        Recipe the rows are produced under.
    extra : Mapping, optional
        Stage-specific metadata copied into the sidecar.
    append : bool, default False
        Continue an existing manifest rather than truncating it.
    """

    def __init__(
        self,
        directory: Path,
        name: str,
        *,
        stage: str,
        study: str = "",
        recipe_hash: str = "",
        extra: Optional[Mapping[str, Any]] = None,
        append: bool = False,
    ) -> None:
        """Open the manifest for writing."""
        self.rows_path, self.info_path = manifest_paths(Path(directory), name)
        self.rows_path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = open(self.rows_path, "a" if append else "w", encoding="utf-8")
        self._fields: set[str] = set()
        self._count = 0
        if append and self.info_path.is_file():
            try:
                previous = read_manifest_info(self.info_path)
                self._count = previous.n_rows
                self._fields.update(previous.fields)
            except ConfigurationError:
                pass
        self.info = ManifestInfo(
            stage=stage,
            study=study,
            recipe_hash=recipe_hash,
            extra=dict(extra or {}),
        )

    def write(self, record: Mapping[str, Any]) -> None:
        """Append one artifact record.

        Parameters
        ----------
        record : Mapping
            JSON-serialisable measurements for a single artifact.  A ``uid``
            key is strongly recommended so selections can reference it.
        """
        payload = dict(record)
        self._fields.update(payload)
        self._stream.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        self._count += 1

    def write_all(self, records: Iterable[Mapping[str, Any]]) -> None:
        """Append many records in order."""
        for record in records:
            self.write(record)

    def close(self) -> None:
        """Flush rows and write the sidecar."""
        if self._stream.closed:
            return
        self._stream.close()
        from rocqipath import __version__

        self.info.n_rows = self._count
        self.info.fields = sorted(self._fields)
        self.info.rocqipath_version = __version__
        self.info.generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.info_path.write_text(
            json.dumps(self.info.to_dict(), indent=2) + "\n", encoding="utf-8"
        )

    def __enter__(self) -> "ManifestWriter":
        """Return this writer for context-manager use."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Close the writer, writing the sidecar even after an exception."""
        self.close()


def read_manifest(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield records from a JSONL manifest.

    Parameters
    ----------
    path : pathlib.Path
        Path to a ``.jsonl`` manifest.

    Yields
    ------
    dict
        One artifact record per line.

    Raises
    ------
    ConfigurationError
        If the file is missing or a line is not valid JSON.
    """
    rows_path = Path(path)
    if not rows_path.is_file():
        raise ConfigurationError(f"No manifest at {rows_path}.")
    with open(rows_path, encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConfigurationError(f"{rows_path}: line {number} is not valid JSON: {exc}")


def read_manifest_info(path: Path) -> ManifestInfo:
    """Read a manifest sidecar.

    Parameters
    ----------
    path : pathlib.Path
        Path to a ``.manifest.json`` sidecar.

    Returns
    -------
    ManifestInfo
        Parsed metadata.

    Raises
    ------
    ConfigurationError
        If the file is missing or malformed.
    """
    info_path = Path(path)
    if not info_path.is_file():
        raise ConfigurationError(f"No manifest sidecar at {info_path}.")
    try:
        return ManifestInfo.from_dict(json.loads(info_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{info_path} is not valid JSON: {exc}") from exc


def summarise_field(records: Sequence[Mapping[str, Any]], name: str) -> Dict[str, float]:
    """Return simple statistics for one numeric manifest field.

    Parameters
    ----------
    records : sequence of Mapping
        Manifest rows.
    name : str
        Field to summarise.

    Returns
    -------
    dict
        ``count``, ``min``, ``max``, ``mean``, and ``median``.  Empty when no
        row carries a numeric value for ``name``.
    """
    values = []
    for record in records:
        value = record.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values.append(float(value))
    if not values:
        return {}
    values.sort()
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0
    return {
        "count": float(len(values)),
        "min": values[0],
        "max": values[-1],
        "mean": sum(values) / len(values),
        "median": median,
    }
