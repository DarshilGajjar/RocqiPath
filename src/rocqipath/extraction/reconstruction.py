"""Reassemble reversible patch sets into pyramidal whole-slide images."""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyvips
from PIL import Image
from tqdm.auto import tqdm

_PATCH_EXTENSIONS = (".png", ".tif", ".tiff", ".jpg", ".jpeg")


def _load_metadata(extractor: Any, case_id: str) -> Dict[str, Any]:
    """Load a reversible extraction manifest for one case."""
    meta_path = os.path.join(
        extractor.output_dir,
        "patch_extraction",
        case_id,
        f"{case_id}_metadata.json",
    )
    with open(meta_path, "r") as file:
        return json.load(file)


def _patch_directory(extractor: Any, case_id: str, mode: str) -> str:
    """Resolve the directory that contains patches for a reconstruction mode."""
    base_folder = os.path.join(extractor.output_dir, "patch_extraction", case_id)
    if mode.lower() == "predicted_ihc":
        return os.path.join(base_folder, "predicted_ihc")
    return base_folder


def _index_patch_files(patch_dir: str) -> Dict[str, List[str]]:
    """Index image paths by every six-digit identifier in their filenames."""
    file_index: Dict[str, List[str]] = {}
    for filename in os.listdir(patch_dir):
        if not filename.lower().endswith(_PATCH_EXTENSIONS):
            continue
        for patch_id in re.findall(r"(\d{6})", filename):
            file_index.setdefault(patch_id, []).append(os.path.join(patch_dir, filename))
    return file_index


def _patch_candidates(
    patch_id: str,
    patch_dir: str,
    file_index: Dict[str, List[str]],
) -> List[str]:
    """Return indexed candidates or the historical glob fallback."""
    candidates = file_index.get(patch_id, [])
    if candidates:
        return candidates
    return sorted(
        path
        for path in glob.glob(os.path.join(patch_dir, f"*{patch_id}*"))
        if path.lower().endswith(_PATCH_EXTENSIONS)
    )


def _select_patch(candidates: List[str], case_id: str, tag: str) -> str:
    """Resolve ambiguous patch filenames using the historical keyword rule."""
    if len(candidates) == 1:
        return candidates[0]
    return next(
        (
            candidate
            for candidate in candidates
            if case_id.lower() in os.path.basename(candidate).lower()
            or tag in os.path.basename(candidate).lower()
        ),
        candidates[0],
    )


def _assemble_canvas(
    dimensions: Tuple[int, int],
    patches: List[Dict[str, Any]],
    patch_dir: str,
    file_index: Dict[str, List[str]],
    *,
    case_id: str,
    tag: str,
    mode: str,
    overlapping: bool,
) -> Tuple[np.ndarray, Optional[np.ndarray], int, int]:
    """Place every readable patch onto a direct-paste or averaging canvas."""
    width, height = dimensions
    if overlapping:
        canvas = np.zeros((height, width, 3), dtype=np.float32)
        counts: Optional[np.ndarray] = np.zeros((height, width, 1), dtype=np.float32)
    else:
        canvas = np.full((height, width, 3), 255, dtype=np.uint8)
        counts = None

    placed = missing = 0
    for patch in tqdm(patches, desc=f"Assembling [{mode}]"):
        coords, patch_id = patch.get("coordinates"), patch.get("id")
        if coords is None or patch_id is None:
            continue
        x, y = int(coords[0]), int(coords[1])
        candidates = _patch_candidates(patch_id, patch_dir, file_index)
        if not candidates:
            tqdm.write(f"[WARN] Missing patch {patch_id}")
            missing += 1
            continue
        chosen = _select_patch(candidates, case_id, tag)
        try:
            with Image.open(chosen) as image:
                array = np.array(image.convert("RGB"))
            patch_height, patch_width = array.shape[:2]
            if overlapping:
                canvas[y : y + patch_height, x : x + patch_width] += array.astype(np.float32)
                counts[y : y + patch_height, x : x + patch_width] += 1.0
            else:
                canvas[y : y + patch_height, x : x + patch_width] = array
            placed += 1
        except Exception as exc:
            tqdm.write(f"[WARN] Cannot open {chosen}: {exc}")
            missing += 1
    return canvas, counts, placed, missing


def _finalize_canvas(
    canvas: np.ndarray,
    counts: Optional[np.ndarray],
    overlapping: bool,
) -> np.ndarray:
    """Average overlapping pixels or return the direct-paste canvas."""
    if not overlapping:
        return canvas
    counts[counts == 0] = 1.0
    return (canvas / counts).clip(0, 255).astype(np.uint8)


def _save_pyramid(array: np.ndarray, output_path: str) -> None:
    """Write an RGB array as a tiled pyramidal LZW TIFF."""
    height, width = array.shape[:2]
    vips_image = pyvips.Image.new_from_memory(array.tobytes(), width, height, 3, "uchar")
    vips_image.tiffsave(
        output_path,
        tile=True,
        tile_width=512,
        tile_height=512,
        pyramid=True,
        compression="lzw",
        Q=99,
    )


class PatchReconstructionMixin:
    """Provide the inverse operation for reversible patch extraction."""

    def reconstruct_wsi(
        self,
        case_id: str,
        biomarker: str,
        output_path: str,
        mode: str = "he",
        split: str = "test",
    ) -> dict:
        """Reconstruct extracted patches as a pyramidal whole-slide TIFF.

        Parameters
        ----------
        case_id : str
            Case directory and manifest identifier.
        biomarker : str
            Marker token used to disambiguate IHC patch filenames.
        output_path : str
            Root under which ``reconstructed_wsi`` is created.
        mode : {"he", "ihc", "predicted_ihc"}, optional
            Patch channel to assemble.
        split : str, optional
            Retained compatibility argument; it does not alter lookup.

        Returns
        -------
        dict
            ``{"placed": int, "missing": int}``.

        Notes
        -----
        Coordinates are target-magnification pixels from the extraction
        manifest. When stride is smaller than patch size, overlapping
        RGB values are averaged in ``float32``; otherwise patches are
        pasted directly onto a white ``uint8`` canvas.

        See Also
        --------
        rocqipath.extraction.ReversiblePatchExtractor.extract_from_case
            Produce the patches and manifest consumed here.
        """
        save_dir = os.path.join(output_path, "reconstructed_wsi")
        os.makedirs(save_dir, exist_ok=True)
        final_save_path = os.path.join(save_dir, f"{case_id}_{mode}_pyramid.tif")

        metadata = _load_metadata(self, case_id)
        width, height = metadata.get("dimensions", (0, 0))
        patches = metadata.get("patches", [])
        stride = metadata.get("stride", self.patch_size)
        overlapping = stride < self.patch_size
        print(f"[INFO] Canvas     : {width} × {height} px")
        print(f"[INFO] Stride     : {stride}  |  Overlap: {overlapping}")
        print(f"[INFO] Patches    : {len(patches)}")

        patch_dir = _patch_directory(self, case_id, mode)
        if not os.path.isdir(patch_dir):
            print(f"[ERROR] Patch directory not found: {patch_dir}")
            return {"placed": 0, "missing": len(patches)}

        tag = "he" if mode.lower() in ("he", "predicted_ihc") else biomarker.lower()
        canvas, counts, placed, missing = _assemble_canvas(
            (width, height),
            patches,
            patch_dir,
            _index_patch_files(patch_dir),
            case_id=case_id,
            tag=tag,
            mode=mode,
            overlapping=overlapping,
        )
        final_array = _finalize_canvas(canvas, counts, overlapping)
        print(f"[INFO] Writing pyramidal TIFF → {final_save_path}")
        _save_pyramid(final_array, final_save_path)
        print(f"[OK] Saved: {final_save_path}  (placed={placed}, missing={missing})")
        return {"placed": placed, "missing": missing}
