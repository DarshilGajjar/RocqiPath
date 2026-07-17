"""Shared slide reader with exact physical-magnification reads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image

from .magnification import MagnificationPlan, build_magnification_plan, objective_magnification_from_properties

try:
    import openslide
except ImportError:  # pragma: no cover - depends on optional WSI extra
    openslide = None


class SlideReader:
    """Open a WSI with OpenSlide or fall back to PIL for ordinary TIFFs.

    Call :meth:`configure_magnification` before :meth:`read_at_magnification`.
    Coordinates and sizes passed to that method are expressed entirely in the
    target-resolution grid, keeping scanner-specific pyramid details internal.
    """

    def __init__(self, path: str) -> None:
        """Open ``path`` with OpenSlide when possible, otherwise PIL."""
        self.path = str(Path(path))
        self._slide = None
        self._pil = None
        if openslide is not None:
            try:
                self._slide = openslide.OpenSlide(self.path)
            except Exception:
                pass
        if self._slide is None:
            self._pil = Image.open(self.path).convert("RGBA")
        self.plan: Optional[MagnificationPlan] = None

    @property
    def dimensions(self) -> Tuple[int, int]:
        """Level-0 ``(width, height)``."""
        return self._slide.dimensions if self._slide is not None else self._pil.size

    @property
    def properties(self) -> Dict[str, Any]:
        """Slide metadata, empty for PIL-backed files."""
        return dict(self._slide.properties) if self._slide is not None else {}

    @property
    def level_downsamples(self) -> Tuple[float, ...]:
        """Native pyramid downsample factors."""
        if self._slide is None:
            return (1.0,)
        return tuple(float(value) for value in self._slide.level_downsamples)

    def configure_magnification(
        self, target_magnification: float, source_magnification: Optional[float] = None
    ) -> MagnificationPlan:
        """Resolve and cache the exact target-magnification plan."""
        fallback = source_magnification or self._manifest_magnification()
        base, _ = objective_magnification_from_properties(
            self.properties, fallback=fallback
        )
        self.plan = build_magnification_plan(
            base, target_magnification, self.level_downsamples
        )
        return self.plan

    def _manifest_magnification(self) -> Optional[float]:
        """Read magnification recorded by RocqiPath beside an extracted TIFF."""
        source = Path(self.path)
        candidates = [
            source.with_name(f"{source.stem}_manifest.json"),
            source.parent / "manifest.json",
        ]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                value = payload.get("output_magnification")
                if value is not None and float(value) > 0:
                    return float(value)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return None

    @property
    def target_dimensions(self) -> Tuple[int, int]:
        """Image dimensions at the configured physical zoom."""
        if self.plan is None:
            raise RuntimeError("configure_magnification() must be called first")
        return self.plan.target_dimensions(self.dimensions)

    def read_at_magnification(
        self, location: Tuple[int, int], size: Tuple[int, int]
    ) -> Image.Image:
        """Read target-grid coordinates at the exact configured zoom."""
        if self.plan is None:
            raise RuntimeError("configure_magnification() must be called first")
        location0 = self.plan.target_to_level0(location)
        if self._slide is not None:
            image = self._slide.read_region(
                location0, self.plan.level, self.plan.native_read_size(size)
            )
        else:
            x0, y0 = location0
            scale = self.plan.level0_per_target_pixel
            source_size = (
                max(1, int(round(size[0] * scale))),
                max(1, int(round(size[1] * scale))),
            )
            image = self._read_pil_region(location0, source_size)
        if image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        return image

    def _read_pil_region(
        self, location: Tuple[int, int], size: Tuple[int, int]
    ) -> Image.Image:
        """Crop a PIL image with white padding outside image bounds."""
        x, y = location
        w, h = size
        iw, ih = self._pil.size
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(iw, x + w), min(ih, y + h)
        region = self._pil.crop((x1, y1, x2, y2))
        if region.size == size:
            return region
        padded = Image.new("RGBA", size, (255, 255, 255, 255))
        padded.paste(region, (x1 - x, y1 - y))
        return padded

    def close(self) -> None:
        """Release the active backend handle."""
        if self._slide is not None:
            self._slide.close()
        if self._pil is not None:
            self._pil.close()

    def __enter__(self) -> "SlideReader":
        """Return this open reader for context-manager use."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Close the reader when leaving a context-manager block."""
        self.close()
