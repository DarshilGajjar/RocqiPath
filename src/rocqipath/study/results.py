"""Turn manifests and selections into the tidy table people actually want.

Every stage writes measurements at artifact granularity.  A result table is
what you get when those measurements are filtered through a selection and
aggregated to the level a figure or a statistics package needs — usually one
row per case and stain.

Because aggregation happens here rather than inside the counting stage,
changing a QC rule changes the table without re-counting a single cell.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.study.selection import Selection

__all__ = ["ResultTable", "aggregate", "write_csv"]


class ResultTable:
    """A list of uniform rows with a stable column order.

    Parameters
    ----------
    rows : sequence of Mapping
        Row records.
    columns : sequence of str, optional
        Explicit column order.  Derived from the rows when omitted.
    """

    def __init__(
        self,
        rows: Sequence[Mapping[str, Any]],
        columns: Optional[Sequence[str]] = None,
    ) -> None:
        """Store rows and resolve the column order."""
        self.rows: List[Dict[str, Any]] = [dict(row) for row in rows]
        if columns is not None:
            self.columns = list(columns)
        else:
            seen: List[str] = []
            for row in self.rows:
                for key in row:
                    if key not in seen:
                        seen.append(key)
            self.columns = seen

    def __len__(self) -> int:
        """Return the number of rows."""
        return len(self.rows)

    def __iter__(self):
        """Iterate over rows."""
        return iter(self.rows)

    def to_dicts(self) -> List[Dict[str, Any]]:
        """Return the rows as plain dictionaries."""
        return [dict(row) for row in self.rows]

    def to_csv(self, path: Path) -> Path:
        """Write the table to ``path`` as CSV and return the path."""
        return write_csv(path, self.rows, self.columns)

    def to_dataframe(self):
        """Return the table as a pandas DataFrame.

        Returns
        -------
        pandas.DataFrame
            The same rows, for downstream statistics.

        Raises
        ------
        ConfigurationError
            If pandas is not installed.  Every other RocqiPath result format
            works without it, so pandas is deliberately not a dependency.
        """
        try:
            import pandas
        except ImportError as exc:
            raise ConfigurationError(
                "to_dataframe() needs pandas, which RocqiPath does not require. "
                "Install it with: python -m pip install pandas — or use "
                "to_dicts()/to_csv() instead."
            ) from exc
        return pandas.DataFrame(self.rows, columns=self.columns)

    def format(self, limit: int = 20) -> str:
        """Render the table as aligned plain text.

        Parameters
        ----------
        limit : int, default 20
            Maximum rows shown before truncation.

        Returns
        -------
        str
            A printable table.
        """
        if not self.rows:
            return "(no rows)"
        shown = self.rows[:limit]
        widths = {
            column: max(len(column), *(len(_render(row.get(column))) for row in shown))
            for column in self.columns
        }
        header = "  ".join(column.ljust(widths[column]) for column in self.columns)
        divider = "  ".join("-" * widths[column] for column in self.columns)
        body = [
            "  ".join(_render(row.get(column)).ljust(widths[column]) for column in self.columns)
            for row in shown
        ]
        text = "\n".join([header, divider, *body])
        if len(self.rows) > limit:
            text += f"\n... {len(self.rows) - limit} more row(s)"
        return text


def _render(value: Any) -> str:
    """Render one cell value for plain-text display."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _numeric(value: Any) -> Optional[float]:
    """Return ``value`` as a float when it is numeric, otherwise ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def aggregate(
    records: Iterable[Mapping[str, Any]],
    *,
    group_by: Sequence[str] = ("case", "stain"),
    sum_fields: Sequence[str] = (),
    mean_fields: Sequence[str] = (),
    selection: Optional[Selection] = None,
    uid_field: str = "uid",
) -> ResultTable:
    """Aggregate manifest rows into one row per group.

    Parameters
    ----------
    records : iterable of Mapping
        Manifest rows.
    group_by : sequence of str, default ("case", "stain")
        Fields defining a group.
    sum_fields : sequence of str, optional
        Numeric fields summed within each group.
    mean_fields : sequence of str, optional
        Numeric fields averaged within each group.
    selection : Selection, optional
        Restrict to artifacts in this selection before aggregating.
    uid_field : str, default "uid"
        Field carrying each artifact's identifier.

    Returns
    -------
    ResultTable
        One row per group, with an ``n`` count column.
    """
    allowed = set(selection.uids) if selection is not None else None
    buckets: Dict[tuple, Dict[str, Any]] = {}
    totals: Dict[tuple, Dict[str, List[float]]] = {}

    for record in records:
        if allowed is not None and str(record.get(uid_field)) not in allowed:
            continue
        key = tuple(record.get(field) for field in group_by)
        bucket = buckets.setdefault(key, {field: record.get(field) for field in group_by})
        bucket["n"] = int(bucket.get("n", 0)) + 1
        store = totals.setdefault(key, {})
        for field in sum_fields:
            value = _numeric(record.get(field))
            if value is not None:
                bucket[field] = float(bucket.get(field, 0.0)) + value
        for field in mean_fields:
            value = _numeric(record.get(field))
            if value is not None:
                store.setdefault(field, []).append(value)

    for key, values in totals.items():
        for field, collected in values.items():
            buckets[key][f"{field}_mean"] = sum(collected) / len(collected)

    columns = (
        list(group_by)
        + ["n"]
        + [field for field in sum_fields]
        + [f"{field}_mean" for field in mean_fields]
    )
    rows = [buckets[key] for key in sorted(buckets, key=lambda item: tuple(str(v) for v in item))]
    return ResultTable(
        rows, columns=[column for column in columns if any(column in r for r in rows)]
    )


def write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    columns: Optional[Sequence[str]] = None,
) -> Path:
    """Write rows to a CSV file.

    Parameters
    ----------
    path : pathlib.Path
        Destination file, whose parent is created if missing.
    rows : sequence of Mapping
        Rows to write.
    columns : sequence of str, optional
        Column order.  Derived from the rows when omitted.

    Returns
    -------
    pathlib.Path
        The path written.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        seen: List[str] = []
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.append(key)
        columns = seen
    with open(destination, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in columns})
    return destination
