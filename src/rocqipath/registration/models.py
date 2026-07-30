"""Data containers returned by the alignment pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class CaseContext:
    """Metadata bundle for a single reference/moving slide pair."""

    case_id: str  # e.g. "sample_0001_marker_a"
    sample_id: str  # e.g. "sample_0001"
    pair_name: str  # e.g. "serial_section_01" or "cd8"
    reference_file: str  # absolute path to the fixed/reference WSI
    moving_file: str  # absolute path to the moving WSI
    grids: List[int] = field(default_factory=list)

    @classmethod
    def from_paths(
        cls,
        reference_path: str,
        moving_path: str,
        pair_name: str,
        *,
        sample_id: Optional[str] = None,
    ) -> "CaseContext":
        """Construct a case context from reference and moving paths.

        When *sample_id* is omitted it is derived from the reference filename
        stem (everything before the first ``_``).
        """
        if sample_id is None:
            sample_id = Path(reference_path).stem.split("_")[0]
        return cls(
            case_id=f"{sample_id}_{pair_name.lower()}",
            sample_id=sample_id,
            pair_name=pair_name,
            reference_file=str(Path(reference_path).resolve()),
            moving_file=str(Path(moving_path).resolve()),
        )


@dataclass
class AlignedCaseResult:
    """Outcome of aligning one WSI pair."""

    case: CaseContext
    registrar: Any  # WSIRegistrar instance, or None in dry-run
    thumb: Any  # Grid-map PIL.Image, or None
    valid_grids: List[int]  # Grid indices that passed tissue QC
    aligned_moving_path: Optional[str] = None
