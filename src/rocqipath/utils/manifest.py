"""Manifest JSON read, write, validation, and resume helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def region_outputs_exist(region_dir: Path, tag: str) -> bool:
    """Return whether a region's TIFF, preview, and manifest all exist."""
    return all(
        [
            (region_dir / f"{tag}.tif").exists(),
            (region_dir / f"{tag}_preview.jpg").exists(),
            (region_dir / f"{tag}_manifest.json").exists(),
        ]
    )


def write_region_manifest(
    manifest_path: Path,
    *,
    pipeline: str,
    sample_id: str,
    region_number: int,
    source_file: str,
    rel_box: dict[str, float],
    abs_box: dict[str, int],
    full_slide_dims: dict[str, int],
    detection_source: str,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    """Write one extracted region's provenance and geometry manifest."""
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest: dict[str, Any] = {
        "generated_at": generated_at,
        "pipeline": pipeline,
        "sample_id": sample_id,
        "region_number": region_number,
        "source_file": source_file,
        "detection_source": detection_source,
        "coordinates": {"relative": rel_box, "absolute_pixels": abs_box},
        "full_slide_dims": full_slide_dims,
    }
    if extra_meta:
        manifest.update(extra_meta)
    with open(manifest_path, "w") as stream:
        json.dump(manifest, stream, indent=2)


def write_slide_manifest(
    path: Path,
    *,
    pipeline: str,
    sample_id: str,
    source_file: str,
    n_regions: int,
    regions: list[dict[str, Any]],
) -> None:
    """Write a slide-level summary for every extracted region."""
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with open(path, "w") as stream:
        json.dump(
            {
                "generated_at": generated_at,
                "pipeline": pipeline,
                "sample_id": sample_id,
                "source_file": source_file,
                "n_regions": n_regions,
                "regions": regions,
            },
            stream,
            indent=2,
        )


def load_manifest(manifest_path: str) -> dict[str, Any]:
    """Load and validate a WSI-comparison case manifest."""
    if not Path(manifest_path).is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with open(manifest_path, encoding="utf-8") as stream:
        manifest = json.load(stream)
    required_keys = {"case_id", "model", "split", "wsi_dir", "stains"}
    missing = required_keys - manifest.keys()
    if missing:
        raise ValueError(f"Manifest is missing required keys: {missing}")
    required_stains = {"gt_he", "gt_ihc", "prediction_ihc"}
    missing_stains = required_stains - manifest["stains"].keys()
    if missing_stains:
        raise ValueError(
            f"Manifest stains block is incomplete. Missing: {missing_stains}. "
            f"Have you run wsi_reconstruction.py for all three stain types?"
        )
    return manifest


__all__ = [
    "load_manifest",
    "region_outputs_exist",
    "write_region_manifest",
    "write_slide_manifest",
]
