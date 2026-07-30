"""Stateless filename parsing, natural sorting, and sample-ID helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Pattern

DEFAULT_REFERENCE_NAME = "reference"
DEFAULT_MOVING_NAME = "moving"
DEFAULT_HE_KEYWORDS = ("hne", "h&e", "he")
DEFAULT_IHC_KEYWORDS = (
    "cd8",
    "cd31",
    "caix",
    "meca79",
    "cd3",
    "cd56",
    "cd68",
    "cd163",
    "mhc1",
    "pdl1",
)


def natural_sort_key(value: str | Path) -> list[tuple[int, int | str]]:
    """Return a case-insensitive natural-sort key for a path-like value."""
    return [
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.split(r"(\d+)", str(value))
    ]


def build_filename_pattern(
    reference_name: str = DEFAULT_REFERENCE_NAME,
    moving_name: str = DEFAULT_MOVING_NAME,
) -> str:
    """Build the generalized ``<sample_id>_<role>.<ext>`` filename regex."""
    return (
        r"^(?P<sample_id>.+?)_"
        rf"(?P<role>{re.escape(reference_name)}|{re.escape(moving_name)})"
        r"(?:\.[^.]+)+$"
    )


def parse_wsi_filename(filename: str, pattern: Pattern[str]) -> tuple[str, str] | None:
    """Parse a WSI basename into its sample identifier and lowercase role."""
    match = pattern.match(Path(filename).name)
    if not match:
        return None
    return match.group("sample_id"), match.group("role").lower()


def extract_sample_id(
    filename: str,
    extra_keywords: tuple[str, ...] = (),
    *,
    he_keywords: tuple[str, ...] = DEFAULT_HE_KEYWORDS,
    ihc_keywords: tuple[str, ...] = DEFAULT_IHC_KEYWORDS,
) -> str:
    """Strip known stain keywords from a filename and return its sample ID."""
    stem = Path(filename).stem
    all_keywords = sorted(
        he_keywords + ihc_keywords + extra_keywords,
        key=len,
        reverse=True,
    )
    pattern = "|".join(re.escape(keyword) for keyword in all_keywords)
    cleaned = re.sub(rf"[-_]?(?:{pattern})[-_]?", "_", stem, flags=re.IGNORECASE)
    return re.sub(r"_+", "_", cleaned).strip("_")


__all__ = [
    "DEFAULT_HE_KEYWORDS",
    "DEFAULT_IHC_KEYWORDS",
    "DEFAULT_MOVING_NAME",
    "DEFAULT_REFERENCE_NAME",
    "build_filename_pattern",
    "extract_sample_id",
    "natural_sort_key",
    "parse_wsi_filename",
]
