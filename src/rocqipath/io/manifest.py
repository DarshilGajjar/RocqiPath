"""Manifest JSON read, write, validation, and resume helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


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
    extra_meta: dict[str, Any] | None = None,
) -> None:
    """Write a slide-level summary for every extracted region."""
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "generated_at": generated_at,
        "pipeline": pipeline,
        "sample_id": sample_id,
        "source_file": source_file,
        "n_regions": n_regions,
        "regions": regions,
    }
    if extra_meta:
        manifest.update(extra_meta)
    with open(path, "w") as stream:
        json.dump(manifest, stream, indent=2)


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


#: File name of the run manifest every workflow writes into its output folder.
RUN_MANIFEST = "rocqipath.json"
#: Version of the run-manifest layout; bump when it changes incompatibly.
RUN_MANIFEST_SCHEMA = 1


def _json_safe(value: Any) -> Any:
    """Convert values json cannot encode (paths, classes, numpy scalars)."""
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return repr(value) if isinstance(value, type) else str(value)


def _relative(path: Path, root: Path) -> str:
    """Store paths inside ``root`` relative to it so folders can be moved."""
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(Path(path).resolve())


def write_run_manifest(result: Any, inputs: Any = ()) -> Path:
    """Record a workflow run in ``<output_dir>/rocqipath.json``.

    One folder may hold the output of several workflows (for example
    training and applying a stain normalizer); each workflow's latest run is
    kept under its name.

    Parameters
    ----------
    result : rocqipath.Result
        The finished run.
    inputs : iterable of path
        The inputs it consumed, recorded for provenance.

    Returns
    -------
    pathlib.Path
        The manifest file.
    """
    from rocqipath import __version__

    root = Path(result.output_dir)
    path = root / RUN_MANIFEST
    runs: Dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("schema") == RUN_MANIFEST_SCHEMA:
                runs = dict(existing.get("runs", {}))
        except ValueError:
            runs = {}
    runs[result.workflow] = {
        "rocqipath_version": __version__,
        "created": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "config": result.config.to_dict() if result.config is not None else None,
        "inputs": [str(Path(p).resolve()) for p in inputs],
        "summary": result.summary,
        "items": [
            {
                "sample_id": item.sample_id,
                "role": item.role,
                "path": _relative(item.path, root),
                "magnification": item.magnification,
                "source": str(item.source) if item.source is not None else None,
                "meta": item.meta,
            }
            for item in result.items
        ],
    }
    manifest = {"schema": RUN_MANIFEST_SCHEMA, "runs": runs}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, default=_json_safe), encoding="utf-8")
    temporary.replace(path)
    return path


def read_run_manifest(folder: str | Path) -> list:
    """Read the results recorded in ``<folder>/rocqipath.json``.

    Parameters
    ----------
    folder : str or pathlib.Path
        A workflow output folder.

    Returns
    -------
    list of rocqipath.Result
        One result per workflow run recorded there. Item paths are absolute
        again; ``config`` is rebuilt when the workflow is registered.

    Raises
    ------
    FileNotFoundError
        If the folder has no run manifest.
    ValueError
        If the manifest uses an unknown schema version.
    """
    from rocqipath.registry import WORKFLOWS, Item, Result

    root = Path(folder).resolve()
    path = root / RUN_MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"No {RUN_MANIFEST} in {root}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != RUN_MANIFEST_SCHEMA:
        raise ValueError(
            f"{path} uses manifest schema {manifest.get('schema')!r}; "
            f"this RocqiPath reads schema {RUN_MANIFEST_SCHEMA}"
        )
    results = []
    for name, run in manifest.get("runs", {}).items():
        config = None
        if name in WORKFLOWS and run.get("config") is not None:
            try:
                config = WORKFLOWS[name].config.from_dict(run["config"])
            except (TypeError, ValueError):
                config = None
        items = tuple(
            Item(
                sample_id=entry["sample_id"],
                role=entry["role"],
                path=(root / entry["path"]).resolve(),
                magnification=entry.get("magnification"),
                source=Path(entry["source"]) if entry.get("source") else None,
                meta=entry.get("meta") or {},
            )
            for entry in run.get("items", [])
        )
        results.append(
            Result(
                workflow=name,
                output_dir=root,
                items=items,
                summary=run.get("summary") or {},
                config=config,
                manifest_path=path,
            )
        )
    return results


__all__ = [
    "RUN_MANIFEST",
    "RUN_MANIFEST_SCHEMA",
    "load_manifest",
    "read_run_manifest",
    "region_outputs_exist",
    "write_region_manifest",
    "write_run_manifest",
    "write_slide_manifest",
]
