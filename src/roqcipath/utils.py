"""Small file-discovery helpers shared by public APIs and pipelines."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

WSI_EXTENSIONS = (".svs", ".tif", ".tiff", ".ndpi", ".scn", ".mrxs", ".vms", ".vmu")


def detect_wsi_format(path: str) -> Optional[str]:
    """Return the recognized WSI extension for ``path``, or ``None``."""
    name = Path(path).name.lower()
    if name.endswith(".ome.tiff"):
        return ".ome.tiff"
    if name.endswith(".ome.tif"):
        return ".ome.tif"
    return next((ext for ext in WSI_EXTENSIONS if name.endswith(ext)), None)


def list_wsi_files(directory: str, *, recursive: bool = False) -> List[str]:
    """List recognized WSI filenames in deterministic natural order.

    Paths are returned relative to ``directory`` when ``recursive=True`` and as
    basenames otherwise, matching the historical RocqiPath API.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    candidates = root.rglob("*") if recursive else root.iterdir()
    files = [p.relative_to(root).as_posix() for p in candidates if p.is_file() and detect_wsi_format(p.name)]
    return sorted(files, key=lambda s: [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", s)])


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
        marker_match = re.search(
            rf"(?:^|[_ .-]){re.escape(marker)}(?=$|[_ .-])", lowered
        ) if marker else None
        kind = "hne" if hne_match else ("ihc" if marker_match else "")
        if kind:
            grouped.setdefault(suffix, {"hne": [], "ihc": []})[kind].append(filename)
    pairs = []
    for suffix, channels in sorted(grouped.items()):
        if len(channels["hne"]) == len(channels["ihc"]) == 1:
            pairs.append({"suffix": suffix, "hne": channels["hne"][0], "ihc": channels["ihc"][0]})
    return pairs
