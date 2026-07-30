"""Physical magnification utilities shared by WSI processing pipelines.

RocqiPath represents zoom as an objective magnification (for example, 20x),
not as a pyramid-level number.  Pyramid levels are slide-specific: level 1 may
mean 10x on one scanner and 40x on another.  The helpers in this module resolve
the closest native level and describe the final resize needed to produce an
exact, consistent target magnification.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log
from typing import Any, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DEFAULT_TARGET_MAGNIFICATION",
    "MagnificationPlan",
    "build_magnification_plan",
    "objective_magnification_from_properties",
]

DEFAULT_TARGET_MAGNIFICATION = 20.0

_OBJECTIVE_KEYS = (
    "openslide.objective-power",
    "aperio.AppMag",
    "hamamatsu.SourceLens",
    "objective-power",
    "objective_power",
)


def _positive_float(value: Any) -> Optional[float]:
    """Return ``value`` as a positive finite float, otherwise ``None``."""
    if value is None:
        return None
    try:
        parsed = float(str(value).strip().rstrip("xX"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 and isfinite(parsed) else None


def objective_magnification_from_properties(
    properties: Mapping[str, Any], *, fallback: Optional[float] = None
) -> Tuple[float, str]:
    """Resolve the level-0 objective magnification from slide metadata.

    Parameters
    ----------
    properties:
        OpenSlide- or libvips-style metadata mapping.
    fallback:
        Explicit value used only when no supported metadata key is present.
        Supplying a scanner-specific fallback is recommended for metadata-poor
        TIFFs.  If omitted and metadata is missing, a ``ValueError`` is raised
        rather than silently processing at the wrong physical resolution.

    Returns
    -------
    tuple
        ``(magnification, source_key)``. ``source_key`` is ``"fallback"``
        when the explicit fallback was used.
    """
    for key in _OBJECTIVE_KEYS:
        value = _positive_float(properties.get(key))
        if value is not None:
            return value, key
    value = _positive_float(fallback)
    if value is not None:
        return value, "fallback"
    raise ValueError(
        "Slide objective magnification is missing. Set source_magnification "
        "explicitly (for example, 80.0 for an 80x TMA scan)."
    )


@dataclass(frozen=True)
class MagnificationPlan:
    """Resolved read plan for producing pixels at one physical magnification.

    ``level`` is the closest native pyramid level. ``resize_factor`` converts
    pixels read at that level to the exact requested magnification. A value
    below one downsamples; a value above one upsamples.
    """

    base_magnification: float
    target_magnification: float
    level: int
    level_downsample: float
    native_magnification: float
    resize_factor: float

    @property
    def level0_per_target_pixel(self) -> float:
        """Number of level-0 pixels represented by one output pixel."""
        return self.base_magnification / self.target_magnification

    def target_dimensions(self, level0_dimensions: Tuple[int, int]) -> Tuple[int, int]:
        """Convert level-0 ``(width, height)`` to exact target dimensions."""
        scale = self.target_magnification / self.base_magnification
        return tuple(max(1, int(round(v * scale))) for v in level0_dimensions)  # type: ignore[return-value]

    def target_to_level0(self, location: Tuple[int, int]) -> Tuple[int, int]:
        """Map an output-grid location to level-0 OpenSlide coordinates."""
        scale = self.level0_per_target_pixel
        return int(round(location[0] * scale)), int(round(location[1] * scale))

    def native_read_size(self, output_size: Tuple[int, int]) -> Tuple[int, int]:
        """Return native-level pixels needed before exact-scale resizing."""
        scale = self.native_magnification / self.target_magnification
        return tuple(max(1, int(round(v * scale))) for v in output_size)  # type: ignore[return-value]


def build_magnification_plan(
    base_magnification: float,
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION,
    level_downsamples: Sequence[float] = (1.0,),
) -> MagnificationPlan:
    """Select the native pyramid level closest to ``target_magnification``.

    The comparison uses log-distance, making 10x versus 20x as distant as 20x
    versus 40x.  A final resize factor is retained so output is exactly the
    requested zoom even when a scanner pyramid lacks a matching native level.
    """
    base = _positive_float(base_magnification)
    target = _positive_float(target_magnification)
    if base is None or target is None:
        raise ValueError("base_magnification and target_magnification must be > 0")
    if target > base:
        raise ValueError(
            f"target_magnification ({target:g}x) cannot exceed the slide's "
            f"level-0 magnification ({base:g}x)."
        )
    downsamples = [_positive_float(v) for v in level_downsamples]
    if not downsamples or any(v is None for v in downsamples):
        raise ValueError("level_downsamples must contain positive finite values")
    native = [base / float(ds) for ds in downsamples]
    level = min(range(len(native)), key=lambda i: abs(log(native[i] / target)))
    native_mag = native[level]
    return MagnificationPlan(
        base_magnification=base,
        target_magnification=target,
        level=level,
        level_downsample=float(downsamples[level]),
        native_magnification=native_mag,
        resize_factor=target / native_mag,
    )
