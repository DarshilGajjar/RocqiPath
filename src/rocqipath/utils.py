"""Deterministic file-discovery helpers shared by public APIs and pipelines."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Sequence, Tuple, Union

WSI_EXTENSIONS = (".svs", ".tif", ".tiff", ".ndpi", ".scn", ".mrxs", ".vms", ".vmu")


def natural_sort_key(value: Union[str, Path]) -> List[Tuple[int, Union[int, str]]]:
    """Return a case-insensitive natural-sort key for a path-like value."""
    return [
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.split(r"(\d+)", str(value))
    ]


def detect_wsi_format(path: str) -> Optional[str]:
    """Return the recognized WSI extension for ``path``, or ``None``."""
    name = Path(path).name.lower()
    if name.endswith(".ome.tiff"):
        return ".ome.tiff"
    if name.endswith(".ome.tif"):
        return ".ome.tif"
    return next((ext for ext in WSI_EXTENSIONS if name.endswith(ext)), None)


def is_wsi_file(path: Union[str, Path]) -> bool:
    """Return whether ``path`` has a recognized WSI extension."""
    return detect_wsi_format(str(path)) is not None


def list_wsi_files(directory: str, *, recursive: bool = False) -> List[str]:
    """List recognized WSI filenames in deterministic natural order.

    Paths are returned relative to ``directory`` when ``recursive=True`` and as
    basenames otherwise, matching the historical RocqiPath API.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    candidates = root.rglob("*") if recursive else root.iterdir()
    files = [
        p.relative_to(root).as_posix() for p in candidates if p.is_file() and is_wsi_file(p.name)
    ]
    return sorted(files, key=natural_sort_key)


def discover_matching_files(
    directory: Union[str, Path], pattern: Pattern[str], *, group: str = "sample_id"
) -> List[Tuple[str, str]]:
    """Recursively discover filenames matching ``pattern``.

    Returns ``(captured_group, absolute_path)`` pairs in deterministic order.
    The helper is shared by current and compatibility extraction APIs so their
    discovery behavior cannot drift apart.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    matches: List[Tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        match = pattern.match(path.name)
        if match:
            matches.append((match.group(group), str(path.resolve())))
    return sorted(matches, key=lambda item: (natural_sort_key(item[0]), natural_sort_key(item[1])))


def find_aligned_wsi(
    aligned_dir: Union[str, Path],
    biomarker: str,
    sample_id: str,
    reference_channel: str,
) -> Optional[str]:
    """Resolve one aligned target WSI for an extraction case.

    Ambiguous candidates are resolved deterministically by preferring a unique
    filename containing the biomarker, then ``ihc``, then ``aligned``.
    """
    case_dir = Path(aligned_dir) / biomarker / f"{sample_id}_{reference_channel}"
    if not case_dir.is_dir():
        return None
    hits = sorted(
        (path for path in case_dir.glob("*.ome.tif*") if path.is_file()),
        key=natural_sort_key,
    )
    if not hits:
        return None
    if len(hits) == 1:
        return str(hits[0].resolve())
    for keyword in (biomarker.lower(), "ihc", "aligned"):
        preferred = [path for path in hits if keyword in path.name.lower()]
        if len(preferred) == 1:
            return str(preferred[0].resolve())
    return str(hits[0].resolve())


def discover_patch_pairs(directory: Union[str, Path]) -> List[Tuple[str, str, str]]:
    """Discover paired patch images from manifests or supported filenames.

    Manifest-declared channel paths are authoritative. The historical
    ``*_reference.png``/``*_moving.png`` and ``HnE``/``IHC`` layouts remain
    readable as deterministic fallbacks.
    """
    root = Path(directory)
    if not root.is_dir():
        return []

    pairs: List[Tuple[str, str, str]] = []
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


def find_hne_ihc_pairs_by_suffix(files: Sequence[str], biomarker: str) -> List[Dict[str, str]]:
    """Pair H&E and biomarker slides using their shared terminal sample token.

    The function supports names such as ``TMA_HnE_mF1.tif`` and
    ``TMA_CD8_mF1.tif``. The token following the final underscore is treated as
    the sample suffix. Ambiguous duplicates are ignored to prevent silent
    pairing with the wrong slide.
    """
    marker = biomarker.lower().replace("&", "")
    grouped: Dict[str, Dict[str, List[str]]] = {}
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
