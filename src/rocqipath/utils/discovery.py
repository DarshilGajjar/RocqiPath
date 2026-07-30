"""Deterministic filesystem discovery and pairing helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Literal, Pattern, Sequence

from rocqipath.core.logging import logger

from .naming import (
    DEFAULT_MOVING_NAME,
    DEFAULT_REFERENCE_NAME,
    natural_sort_key,
    parse_wsi_filename,
)

WSI_EXTENSIONS = (".svs", ".tif", ".tiff", ".ndpi", ".scn", ".mrxs", ".vms", ".vmu")
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"})


def ensure_directory(path: str | Path, *, create: bool = True) -> Path:
    """Resolve a directory path and optionally create it."""
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        if create:
            resolved.mkdir(parents=True, exist_ok=True)
        else:
            raise FileNotFoundError(f"Directory not found: {resolved}")
    return resolved


def detect_wsi_format(path: str) -> str | None:
    """Return the recognized WSI extension for ``path``, or ``None``."""
    name = Path(path).name.lower()
    if name.endswith(".ome.tiff"):
        return ".ome.tiff"
    if name.endswith(".ome.tif"):
        return ".ome.tif"
    return next((ext for ext in WSI_EXTENSIONS if name.endswith(ext)), None)


def is_wsi_file(path: str | Path) -> bool:
    """Return whether ``path`` has a recognized WSI extension."""
    return detect_wsi_format(str(path)) is not None


def list_wsi_files(
    directory: str | Path,
    *,
    recursive: bool = False,
    sort_mode: Literal["natural", "casefold"] = "natural",
) -> list[str]:
    """List recognized WSI filenames using the requested historical ordering."""
    root = Path(directory)
    if not root.is_dir():
        return []
    candidates = root.rglob("*") if recursive else root.iterdir()
    files = [
        path.relative_to(root).as_posix()
        for path in candidates
        if path.is_file() and is_wsi_file(path.name)
    ]
    if sort_mode == "natural":
        key = natural_sort_key
    elif sort_mode == "casefold":
        key = str.lower
    else:
        raise ValueError(f"Unknown WSI sort mode: {sort_mode!r}")
    return sorted(files, key=key)


def discover_matching_files(
    directory: str | Path,
    pattern: Pattern[str],
    *,
    group: str = "sample_id",
) -> list[tuple[str, str]]:
    """Recursively discover filenames matching ``pattern``."""
    root = Path(directory)
    if not root.is_dir():
        return []
    matches: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        match = pattern.match(path.name)
        if match:
            matches.append((match.group(group), str(path.resolve())))
    return sorted(matches, key=lambda item: (natural_sort_key(item[0]), natural_sort_key(item[1])))


def discover_pair_folders(
    input_dir: str | Path,
    reference_name: str = DEFAULT_REFERENCE_NAME,
    moving_name: str = DEFAULT_MOVING_NAME,
) -> list[str]:
    """Return direct subfolders containing a reference or moving directory."""
    root = Path(input_dir)
    found: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / reference_name).is_dir() or (entry / moving_name).is_dir():
            found.append(entry.name)
    return found


def index_pair_folder(
    pair_path: str | Path,
    pattern: Pattern[str],
    reference_name: str = DEFAULT_REFERENCE_NAME,
    moving_name: str = DEFAULT_MOVING_NAME,
) -> dict[tuple[str, str], str]:
    """Index reference/moving slides by sample ID while preserving first duplicates."""
    root = Path(pair_path)
    index: dict[tuple[str, str], str] = {}
    for label, role in ((reference_name, "reference"), (moving_name, "moving")):
        subdir = root / label
        if not subdir.is_dir():
            continue
        for path in sorted(subdir.iterdir()):
            if not path.is_file() or not is_wsi_file(path.name):
                continue
            parsed = parse_wsi_filename(path.name, pattern)
            if parsed is None:
                logger.warning(f"Filename did not match pattern, skipping: {path.name}")
                continue
            sample_id, parsed_role = parsed
            if parsed_role != label.lower():
                logger.warning(
                    f"Role mismatch for {path.name}: filename says {parsed_role!r}, "
                    f"but file is inside {label!r}; skipping"
                )
                continue
            key = (sample_id, role)
            if key in index:
                logger.warning(f"Duplicate key {key!r} — keeping first. Ignoring: {path}")
            else:
                index[key] = str(path)
    return index


def build_sample_pairs(
    index: dict[tuple[str, str], str],
) -> list[tuple[str, str, str]]:
    """Match indexed reference and moving slides by sample identifier."""
    sample_ids = sorted({sample_id for sample_id, _role in index})
    pairs: list[tuple[str, str, str]] = []
    for sample_id in sample_ids:
        reference_path = index.get((sample_id, "reference"))
        moving_path = index.get((sample_id, "moving"))
        if reference_path and moving_path:
            pairs.append((sample_id, reference_path, moving_path))
        else:
            if not reference_path:
                logger.warning(f"{sample_id}: moving slide found but reference is missing")
            if not moving_path:
                logger.warning(f"{sample_id}: reference slide found but moving is missing")
    return pairs


def find_aligned_wsi(
    aligned_dir: str | Path,
    biomarker: str,
    sample_id: str,
    reference_channel: str,
    *,
    priority_keywords: Sequence[str] | None = None,
    sort_mode: Literal["natural", "lexical"] = "natural",
    resolve: bool = True,
    on_event: Callable[[str, Path, list[Path]], None] | None = None,
) -> str | None:
    """Resolve one aligned target WSI using configurable historical tie-breaking."""
    case_dir = Path(aligned_dir) / biomarker / f"{sample_id}_{reference_channel}"
    if not case_dir.is_dir():
        if on_event is not None:
            on_event("missing_directory", case_dir, [])
        return None
    hits = [path for path in case_dir.glob("*.ome.tif*") if path.is_file()]
    if sort_mode == "natural":
        hits = sorted(hits, key=natural_sort_key)
    elif sort_mode == "lexical":
        hits = sorted(hits)
    else:
        raise ValueError(f"Unknown aligned-file sort mode: {sort_mode!r}")
    if not hits:
        if on_event is not None:
            on_event("no_matches", case_dir, [])
        return None
    if len(hits) == 1:
        selected = hits[0]
        return str(selected.resolve() if resolve else selected)
    keywords = (
        tuple(priority_keywords)
        if priority_keywords is not None
        else (biomarker.lower(), "ihc", "aligned")
    )
    for keyword in keywords:
        preferred = [path for path in hits if keyword in path.name.lower()]
        if len(preferred) == 1:
            selected = preferred[0]
            return str(selected.resolve() if resolve else selected)
    if on_event is not None:
        on_event("ambiguous_fallback", case_dir, hits)
    selected = hits[0]
    return str(selected.resolve() if resolve else selected)


def discover_patch_pairs(directory: str | Path) -> list[tuple[str, str, str]]:
    """Discover paired patch images from manifests or supported filenames."""
    root = Path(directory)
    if not root.is_dir():
        return []
    pairs: list[tuple[str, str, str]] = []
    for manifest in sorted(root.glob("*_metadata.json"), key=natural_sort_key):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        for patch in payload.get("patches", []):
            declared = [
                value
                for key, value in patch.items()
                if key.endswith("_path") and isinstance(value, str)
            ]
            if len(declared) < 2:
                continue
            resolved = []
            for value in declared[:2]:
                path = Path(value)
                if not path.is_absolute():
                    path = root / path
                resolved.append(str(path.resolve()))
            if all(Path(path).is_file() for path in resolved):
                pairs.append((resolved[0], resolved[1], str(patch.get("id", ""))))
    if pairs:
        return pairs
    for reference in sorted(root.glob("*_reference.png"), key=natural_sort_key):
        moving = reference.with_name(reference.name.removesuffix("_reference.png") + "_moving.png")
        if moving.is_file():
            pairs.append((str(reference.resolve()), str(moving.resolve()), reference.name))
    if pairs:
        return pairs
    reference_dir, target_dir = root / "HnE", root / "IHC"
    if reference_dir.is_dir() and target_dir.is_dir():
        for reference in sorted(reference_dir.glob("*.png"), key=natural_sort_key):
            target = target_dir / reference.name
            if target.is_file():
                pairs.append((str(reference.resolve()), str(target.resolve()), reference.name))
    return pairs


def find_hne_ihc_pairs_by_suffix(
    files: Sequence[str],
    biomarker: str,
) -> list[dict[str, str]]:
    """Pair H&E and biomarker slides using their shared terminal sample token."""
    import re

    marker = biomarker.lower().replace("&", "")
    grouped: dict[str, dict[str, list[str]]] = {}
    for filename in files:
        stem = Path(filename).stem
        suffix = stem.rsplit("_", 1)[-1]
        lowered = stem.lower()
        hne_match = re.search(r"(?:^|[_ .-])(?:hne|h&e|he)(?=$|[_ .-])", lowered)
        marker_match = (
            re.search(rf"(?:^|[_ .-]){re.escape(marker)}(?=$|[_ .-])", lowered) if marker else None
        )
        kind = "hne" if hne_match else ("ihc" if marker_match else "")
        if kind:
            grouped.setdefault(suffix, {"hne": [], "ihc": []})[kind].append(filename)
    pairs = []
    for suffix, channels in sorted(grouped.items()):
        if len(channels["hne"]) == len(channels["ihc"]) == 1:
            pairs.append({"suffix": suffix, "hne": channels["hne"][0], "ihc": channels["ihc"][0]})
    return pairs


def discover_files(root: str | Path, stains: list[str]) -> list[Path]:
    """Recursively find image files whose path contains a requested stain token."""
    root = Path(root)
    if not stains or "all" in stains:
        return sorted(path for path in root.rglob("*") if path.suffix.lower() in IMAGE_EXTENSIONS)
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix.lower() in IMAGE_EXTENSIONS and any(stain in path.parts for stain in stains)
    )


__all__ = [
    "IMAGE_EXTENSIONS",
    "WSI_EXTENSIONS",
    "build_sample_pairs",
    "detect_wsi_format",
    "discover_files",
    "discover_matching_files",
    "discover_pair_folders",
    "discover_patch_pairs",
    "ensure_directory",
    "find_aligned_wsi",
    "find_hne_ihc_pairs_by_suffix",
    "index_pair_folder",
    "is_wsi_file",
    "list_wsi_files",
]
