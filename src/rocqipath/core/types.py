"""Shared lightweight type aliases and structural protocols."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol, TypeAlias, Union, runtime_checkable

PathLike: TypeAlias = Union[str, Path]
Size2D: TypeAlias = tuple[int, int]
Coordinate2D: TypeAlias = tuple[int, int]
BoundingBox: TypeAlias = tuple[int, int, int, int]
RelativeBox: TypeAlias = Mapping[str, float]
ManifestPayload: TypeAlias = dict[str, Any]


@runtime_checkable
class SlideLike(Protocol):
    """Describe the OpenSlide-style surface used by shared algorithms."""

    dimensions: Size2D
    level_downsamples: tuple[float, ...]
    properties: Mapping[str, Any]


__all__ = [
    "BoundingBox",
    "Coordinate2D",
    "ManifestPayload",
    "PathLike",
    "RelativeBox",
    "Size2D",
    "SlideLike",
]
