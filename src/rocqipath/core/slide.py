"""Shared slide reader with exact physical-magnification reads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from .magnification import (
    MagnificationPlan,
    build_magnification_plan,
    objective_magnification_from_properties,
)

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


def _image_base_name(path: Path) -> str:
    """Return a filename without ordinary or compound image suffixes."""

    name = path.name
    lowered = name.lower()

    compound_suffixes = (
        ".ome.tiff",
        ".ome.tif",
    )

    for suffix in compound_suffixes:
        if lowered.endswith(suffix):
            return name[: -len(suffix)]

    return path.stem


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
        try:
            import openslide
        except (ImportError, OSError):  # optional WSI backend
            openslide = None
        if openslide is not None:
            try:
                self._slide = openslide.OpenSlide(self.path)
            except Exception:
                pass
        if self._slide is None:
            from PIL import Image

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
        self,
        target_magnification: float,
        source_magnification: Optional[float] = None,
    ) -> MagnificationPlan:
        """Resolve and cache an exact target-magnification read plan."""

        if source_magnification is not None:
            base = float(source_magnification)
        else:
            manifest_magnification = self._manifest_magnification()

            base, _source = objective_magnification_from_properties(
                self.properties,
                fallback=manifest_magnification,
            )

        self.plan = build_magnification_plan(
            base,
            target_magnification,
            self.level_downsamples,
        )

        return self.plan

    def _manifest_magnification(self) -> Optional[float]:
        """Read output magnification recorded beside a generated image."""

        source = Path(self.path)
        base_name = _image_base_name(source)

        candidates = [
            # Preferred sidecar:
            # sample_aligned_moving_manifest.json
            source.with_name(
                f"{base_name}_manifest.json"
            ),

            # Backward compatibility:
            # sample_aligned_moving.ome_manifest.json
            source.with_name(
                f"{source.stem}_manifest.json"
            ),

            # Generic directory-level manifest.
            source.parent / "manifest.json",
        ]

        seen: set[Path] = set()

        for candidate in candidates:
            if candidate in seen:
                continue

            seen.add(candidate)

            if not candidate.is_file():
                continue

            try:
                payload = json.loads(
                    candidate.read_text(encoding="utf-8")
                )

                value = payload.get("output_magnification")

                if value is None:
                    continue

                parsed = float(value)

                if parsed > 0:
                    return parsed

            except (
                OSError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ):
                continue

        return None

    @property
    def target_dimensions(self) -> Tuple[int, int]:
        """Image dimensions at the configured physical zoom."""
        if self.plan is None:
            raise RuntimeError("configure_magnification() must be called first")
        return self.plan.target_dimensions(self.dimensions)

    def read_at_magnification(self, location: Tuple[int, int], size: Tuple[int, int]) -> PILImage:
        """Read target-grid coordinates at the exact configured zoom."""
        from PIL import Image

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

    def _read_pil_region(self, location: Tuple[int, int], size: Tuple[int, int]) -> PILImage:
        """Crop a PIL image with white padding outside image bounds."""
        from PIL import Image

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
