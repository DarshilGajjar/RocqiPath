"""
roqcipath.extraction.patch_extraction
=======================================
Two patch-extraction APIs live in this module:

``ReversiblePatchExtractor`` (original)
    Sliding-window extraction pairing H&E slides with their aligned IHC
    counterparts under a fixed ``Sample_NNNN_he.tif`` naming convention,
    plus re-assembling extracted H&E patches back into a full pyramidal
    OME-TIFF (a "reversible" round trip — hence the class name).

``PatchExtractionConfig`` / ``run_patch_extraction`` (current)
    A generalized, config-driven sliding-window extractor: the reference
    channel's filename convention is a caller-supplied regex rather than
    a hardcoded pattern, the reference/target channel names are
    configurable (not fixed to "he"/"ihc"), and case processing can run
    in parallel via ``max_workers``. Prefer this API for new code.

Unlike most other modules in this package, this one predates the unified
:mod:`roqcipath.logger` system and communicates progress via plain
``print()`` statements (prefixed ``[INFO]``, ``[WARN]``, ``[ERROR]``,
``[DEBUG]``, ``[OK]``, ``[SKIP]``, ``[DONE]``) and :mod:`tqdm` progress
bars rather than the Rich-based logging used elsewhere. It has not (yet)
been migrated to the shared logger.

Patch extraction module with reversible patch extraction (sliding-window only)

Expected data structure — ``ReversiblePatchExtractor``
---------------------------------------------------------
::

    aligned_root/
      <biomarker>/
        Sample_0001_he/
            aligned_ihc.ome.tiff

    he_root/
      <biomarker>/
        he/
          Sample_0001_he.tif  (or .tiff)

Expected data structure — ``PatchExtractionConfig`` / ``run_patch_extraction``
----------------------------------------------------------------------------------
::

    he_dir/                                  (searched recursively)
      <sample_id>_<anything>.tif             (matched against he_filename_pattern)

    aligned_dir/
      <biomarker>/
        <sample_id>_<he_channel_name>/
            aligned_target.ome.tiff

Quickstart
----------
Original, fixed-naming API::

    from roqcipath.extraction.patch_extraction import ReversiblePatchExtractor

    extractor = ReversiblePatchExtractor({
        "he_root":            "./data/he",
        "aligned_root":       "./data/aligned",
        "output_dir":         "./results/patches",
        "biomarker_folders":  ["marker_A", "marker_B"],
        "patch_size":         256,
    })
    extractor.run()

Current, config-driven API::

    from roqcipath.extraction.patch_extraction import PatchExtractionConfig, run_patch_extraction

    cfg = PatchExtractionConfig(
        he_dir              = "./organized_dataset/pdgfrb/cd31",
        aligned_dir         = "./organized_dataset/pdgfrb/pdgfrb",
        output_dir          = "./organized_dataset/pdgfrb/extracted_patches",
        biomarker_folders   = ["pdgfrb"],
        he_filename_pattern = r"^(?P<sample_id>[a-zA-Z0-9]+)_cd31_region\\d+\\.tiff?$",
        he_channel_name     = "cd31",
        ihc_channel_name    = "pdgfrb",
        patch_size          = 2048,
        stride              = 2048,
        tissue_threshold    = 0.5,
        max_workers         = 1,
    )
    run_patch_extraction(cfg)
"""

import concurrent.futures
import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyvips
from PIL import Image, PngImagePlugin
from tqdm.auto import tqdm
from roqcipath.magnification import DEFAULT_TARGET_MAGNIFICATION
from roqcipath.output import OutputLayout
from roqcipath.slide import SlideReader as _SlideReader

__all__ = [
    "ReversiblePatchExtractor",
    "PatchExtractionConfig",
    "run_patch_extraction",
]

# WARNING: raising this reduces Pillow's protection against decompression bombs.
PngImagePlugin.MAX_TEXT_CHUNK = 64 * 1024 * 1024


# ── Slide reader with PIL fallback ───────────────────────────────────────────

# ── Main class ────────────────────────────────────────────────────────────────
class ReversiblePatchExtractor:
    """Extract sliding-window H&E/IHC patch pairs from aligned whole-slide images.

    For each H&E slide found under ``he_root`` (matching the naming
    convention ``Sample_NNNN_he.tif``/``.tiff``), locates the
    corresponding aligned IHC OME-TIFF under ``aligned_root``, then walks
    a sliding window across the H&E slide at ``patch_size``/``stride``,
    keeping only tissue-containing patches (per :meth:`_is_tissue`), and
    saves matching H&E and IHC patches side by side with a JSON metadata
    manifest recording each patch's coordinates. "Reversible" refers to
    the companion re-assembly capability (see ``reassemble_from_patches``
    further down in this module — not covered by this class) that can
    stitch extracted patches back into a full pyramidal OME-TIFF.

    See Also
    --------
    run : The main batch entry point — construct an instance, then call
        ``.run()``.
    """

    def __init__(self, cfg: dict):
        """Validate configuration, resolve paths, and print a startup summary.

        Parameters
        ----------
        cfg : dict
            Configuration dict. Required keys:

            - ``"he_root"`` (str) — root directory containing
              ``<biomarker>/he/Sample_NNNN_he.tif`` files.
            - ``"aligned_root"`` (str) — root directory containing
              ``<biomarker>/Sample_NNNN_he/*.ome.tif*`` aligned IHC
              outputs (as produced by the registration pipeline).
            - ``"biomarker_folders"`` (list of str) — which biomarker
              subfolders to process. Required and must be non-empty; see
              Raises below.

            Optional keys:

            - ``"output_dir"`` (str) — where extracted patches are
              written. Defaults to ``"./output"``.
            - ``"patch_size"`` (int) — patch edge length in pixels.
              Defaults to ``256``.
            - ``"stride"`` (int) — sliding-window step size in pixels.
              Defaults to ``patch_size`` (i.e. non-overlapping patches).
            - ``"target_magnification"`` (float) — exact physical zoom for
              both channels. Defaults to ``20.0``. Legacy ``"magnification"``
              is accepted as a physical-value alias.
            - ``"tissue_threshold"`` (float) — minimum fraction of
              non-background pixels (see :meth:`_is_tissue`) for a patch
              to be kept. Defaults to ``0.9``.

        Raises
        ------
        KeyError
            If ``"he_root"`` or ``"aligned_root"`` is missing from
            ``cfg`` (accessed via direct bracket indexing, which raises
            ``KeyError`` rather than silently defaulting, since both
            paths are mandatory for this class to do anything useful).
        ValueError
            If ``"biomarker_folders"`` is missing from ``cfg`` or is
            present but empty — there is deliberately no default
            biomarker list, since silently assuming specific biomarkers
            would make this class dataset-specific rather than general.

        Notes
        -----
        Creates ``output_dir`` if it doesn't exist, prints a startup
        summary of the resolved configuration, and calls
        :meth:`_debug_folders` to list the biomarker subfolders actually
        found on disk (useful for catching path/naming mismatches before
        a long batch run starts).
        """
        self.cfg        = cfg
        self.patch_size = int(cfg.get("patch_size", 256))
        self.stride     = int(cfg.get("stride", self.patch_size))

        self.output_dir       = os.path.abspath(cfg.get("output_dir", "./output"))
        self.he_root          = os.path.abspath(cfg["he_root"])
        self.aligned_root     = os.path.abspath(cfg["aligned_root"])
        # ``magnification`` historically meant a pyramid index. It now means
        # physical objective magnification; use ``target_magnification`` in new code.
        self.target_magnification = float(
            cfg.get("target_magnification", cfg.get("magnification", DEFAULT_TARGET_MAGNIFICATION))
        )
        self.reference_source_magnification = cfg.get("reference_source_magnification")
        self.target_source_magnification = cfg.get("target_source_magnification")
        self.tissue_threshold = cfg.get("tissue_threshold", 0.9)
        if "biomarker_folders" not in cfg or not cfg["biomarker_folders"]:
            raise ValueError(
                "cfg['biomarker_folders'] is required — pass the list of "
                "biomarker/marker folder names to process (e.g. ['marker_A', 'marker_B'], "
                "or whatever labels your dataset uses)."
            )
        self.biomarker_folders = cfg["biomarker_folders"]

        os.makedirs(self.output_dir, exist_ok=True)
        print("[INFO] Initialized Patch Extraction Module...")
        print(f"       HE root          : {self.he_root}")
        print(f"       Aligned root     : {self.aligned_root}")
        print(f"       Output           : {self.output_dir}")
        print(f"       Patch Size       : {self.patch_size}")
        print(f"       Stride           : {self.stride}")
        print(f"       Magnification    : {self.target_magnification:g}x")
        print(f"       Tissue Threshold : {int(self.tissue_threshold * 100)}%")
        self._debug_folders()

    # ── Debug ─────────────────────────────────────────────────────────────────
    def _debug_folders(self):
        """Print the biomarker subfolders actually found under he_root/aligned_root.

        A diagnostic aid called once from :meth:`__init__`: lists the
        immediate subdirectories of ``self.he_root`` and
        ``self.aligned_root`` (if those roots exist) so a mismatch
        between the configured ``biomarker_folders`` and what's actually
        on disk (e.g. a typo or unexpected casing) is visible immediately
        at startup rather than discovered later as "0 cases found".
        """
        if os.path.isdir(self.he_root):
            print(f"[DEBUG] HE biomarker folders: "
                  f"{[d for d in os.listdir(self.he_root) if os.path.isdir(os.path.join(self.he_root, d))]}")
        if os.path.isdir(self.aligned_root):
            print(f"[DEBUG] Aligned biomarker folders: "
                  f"{[d for d in os.listdir(self.aligned_root) if os.path.isdir(os.path.join(self.aligned_root, d))]}")

    # ── Tissue detection ──────────────────────────────────────────────────────
    def _is_tissue(self, image_pil) -> bool:
        """Decide whether a patch contains enough tissue to keep.

        Converts the patch to grayscale and computes the fraction of
        pixels darker than 235 (out of 255) — i.e. not near-white
        background — as a crude tissue-vs-background estimate.

        Parameters
        ----------
        image_pil : PIL.Image.Image
            The patch to test (any PIL mode; converted to ``"L"``
            grayscale internally).

        Returns
        -------
        bool
            ``True`` if the fraction of non-background pixels is at
            least ``self.tissue_threshold`` (configured via
            ``cfg["tissue_threshold"]``, default ``0.9``); ``False``
            otherwise, meaning the patch is mostly blank slide
            background and should be skipped.
        """
        return float(np.mean(np.array(image_pil.convert("L")) < 235)) >= self.tissue_threshold

    # ── File discovery ─────────────────────────────────────────────────────────
    # Matches Sample_0001_he.tif AND Sample_0001_he.tiff (case-insensitive)
    _HE_PAT = re.compile(r"^(Sample_\d{4})_he\.tiff?$", re.IGNORECASE)

    def _scan_he_cases(self) -> List[Tuple[str, str, str]]:
        """Find every H&E slide matching the naming convention under he_root.

        Scans ``self.he_root/<biomarker>/he/`` for each biomarker in
        ``self.biomarker_folders``, matching filenames against
        ``_HE_PAT`` (``Sample_NNNN_he.tif`` or ``.tiff``,
        case-insensitive).

        Returns
        -------
        list of tuple of (str, str, str)
            One ``(sample_id, biomarker, full_path)`` tuple per matched
            H&E file, where ``sample_id`` is e.g. ``"Sample_0001"`` (the
            first regex capture group) and ``biomarker`` is upper-cased.
            Sorted by ``(biomarker, sample_id)``.

        Notes
        -----
        If a biomarker's expected ``he/`` subfolder doesn't exist, a
        warning is printed and that biomarker is skipped (not treated as
        a fatal error) — this allows partial datasets, where not every
        configured biomarker necessarily has H&E slides present.
        """
        out = []
        for biomarker in self.biomarker_folders:
            bio_he_dir = os.path.join(self.he_root, biomarker, "he")
            if not os.path.isdir(bio_he_dir):
                print(f"[WARN] HE subfolder missing: {bio_he_dir}")
                continue
            for fn in os.listdir(bio_he_dir):
                m = self._HE_PAT.match(fn)
                if m:
                    out.append((m.group(1), biomarker.upper(),
                                os.path.join(bio_he_dir, fn)))
        return sorted(out, key=lambda x: (x[1], x[0]))

    def _find_aligned_ihc(self, sample_id: str, biomarker: str) -> Optional[str]:
        """Locate the aligned IHC OME-TIFF for a given sample and biomarker.

        Parameters
        ----------
        sample_id : str
            Sample identifier, e.g. ``"Sample_0001"``, as returned by
            :meth:`_scan_he_cases`.
        biomarker : str
            Biomarker label; used to build the expected case directory
            path and, if disambiguation is needed, as a keyword hint
            (see Notes).

        Returns
        -------
        str or None
            Full path to the resolved aligned IHC file, or ``None`` if
            the expected case directory doesn't exist or contains no
            ``*.ome.tif*`` files (diagnostic messages are printed in
            either case to aid troubleshooting).

        Notes
        -----
        Looks under
        ``self.aligned_root/<biomarker>/<sample_id>_he/*.ome.tif*``.
        If exactly one match is found, it's returned directly. If
        multiple matches exist, disambiguation is attempted by
        preferring a filename containing (in order) the lowercased
        biomarker name, then ``"ihc"``, then ``"aligned"`` — the first
        keyword that narrows the candidates down to exactly one match
        wins. If ambiguity remains even after all three keywords are
        tried, a warning is printed and the first match (alphabetically,
        via :func:`sorted`) is used as a last resort rather than failing
        the whole run.
        """
        case_dir = os.path.join(self.aligned_root, biomarker,
                                f"{sample_id}_he")
        if not os.path.isdir(case_dir):
            print(f"[DEBUG] Case folder not found: {case_dir}")
            return None
        hits = sorted(glob.glob(os.path.join(case_dir, "*.ome.tif*")))
        if not hits:
            print(f"[DEBUG] No .ome.tif* in: {case_dir}  |  contents: {os.listdir(case_dir)}")
            return None
        if len(hits) == 1:
            return hits[0]
        for kw in [biomarker.lower(), "ihc", "aligned"]:
            preferred = [h for h in hits if kw in os.path.basename(h).lower()]
            if len(preferred) == 1:
                return preferred[0]
        print(f"[WARN] Multiple OME-TIFFs; using: {os.path.basename(hits[0])}")
        return hits[0]

    # ── Patch extraction ───────────────────────────────────────────────────────
    def extract_from_case(self, case_id: str, hne_path: str,
                          marker_files: Dict[str, str]):
        """Sliding-window extraction across the whole slide."""
        os_hne     = _SlideReader(hne_path)
        os_markers = {m: _SlideReader(p) for m, p in marker_files.items()}
        os_hne.configure_magnification(
            self.target_magnification, self.reference_source_magnification
        )
        for reader in os_markers.values():
            reader.configure_magnification(
                self.target_magnification, self.target_source_magnification
            )
        w, h = os_hne.target_dimensions
        biomarker  = next(iter(marker_files)).upper()

        case_dir = OutputLayout(self.output_dir).item_dir("patch_extraction", case_id)

        metadata = {
            "case_id": case_id, "dimensions": (w, h),
            "patch_size": self.patch_size, "stride": self.stride,
            "target_magnification": self.target_magnification,
            "extraction_mode": "sliding", "patches": [],
        }
        idx = 1
        tiles_x = (w + self.stride - 1) // self.stride
        tiles_y = (h + self.stride - 1) // self.stride

        with tqdm(total=tiles_x * tiles_y, desc=f"   -> {case_id}",
                  leave=False, unit="patch") as pbar:
            for y in range(0, h, self.stride):
                for x in range(0, w, self.stride):
                    tw = min(self.patch_size, w - x)
                    th = min(self.patch_size, h - y)
                    hne_p = os_hne.read_at_magnification((x, y), (tw, th)).convert("RGB")

                    if self._is_tissue(hne_p):
                        pid  = f"{idx:06d}"
                        hp = case_dir / f"{case_id}_he_patch_{pid}.png"
                        hne_p.save(hp, compression=None)
                        info = {"id": pid,
                                "coordinates": (int(x), int(y)),
                                "size": (int(tw), int(th)),
                                "he_path": str(hp)}
                        for mn, os_m in os_markers.items():
                            mp = os_m.read_at_magnification((x, y), (tw, th)).convert("RGB")
                            mp_path = case_dir / f"{case_id}_{mn}_patch_{pid}.png"
                            mp.save(mp_path, compression=None)
                            mp.close()
                            info[f"{mn}_path"] = str(mp_path)
                        metadata["patches"].append(info)
                        idx += 1

                    hne_p.close()
                    pbar.update(1)

        os_hne.close()
        for os_m in os_markers.values():
            os_m.close()

        meta_path = case_dir / f"{case_id}_metadata.json"
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        tqdm.write(f"  [OK] {case_id}: {idx - 1} patches saved")

    # ── WSI reconstruction (single method, pyvips pyramidal output) ───────────
    def reconstruct_wsi(self, case_id: str, biomarker: str,
                        output_path: str, mode: str = "he",
                        split: str = "test") -> dict:
        """
        Reconstruct a whole-slide image from extracted patches and save as
        a pyramidal TIFF using pyvips.

        Algorithm
        ---------
        1.  Assemble patches onto a numpy canvas.
            - Non-overlapping stride: direct paste (uint8).
            - Overlapping stride:     accumulate + average (float32).
        2.  Convert the final array to a pyvips Image.
        3.  Save as a tiled, pyramidal LZW-compressed TIFF.

        Parameters
        ----------
        mode : 'he' | 'ihc' | 'predicted_ihc'
        """
        save_dir = os.path.join(output_path, "reconstructed_wsi")
        os.makedirs(save_dir, exist_ok=True)
        final_save_path = os.path.join(save_dir,
                                       f"{case_id}_{mode}_pyramid.tif")

        # ── Load metadata ─────────────────────────────────────────────────────
        meta_path = os.path.join(
            self.output_dir, "patch_extraction", case_id, f"{case_id}_metadata.json",
        )
        with open(meta_path, "r") as f:
            metadata = json.load(f)

        w, h     = metadata.get("dimensions", (0, 0))
        patches  = metadata.get("patches", [])
        stride   = metadata.get("stride", self.patch_size)
        is_overlapping = stride < self.patch_size

        print(f"[INFO] Canvas     : {w} × {h} px")
        print(f"[INFO] Stride     : {stride}  |  Overlap: {is_overlapping}")
        print(f"[INFO] Patches    : {len(patches)}")

        # ── Resolve patch directory ───────────────────────────────────────────
        base_folder = os.path.join(self.output_dir, "patch_extraction", case_id)
        if mode.lower() == "predicted_ihc":
            full_patch_dir = os.path.join(base_folder, "predicted_ihc")
        else:
            full_patch_dir = base_folder

        if not os.path.isdir(full_patch_dir):
            print(f"[ERROR] Patch directory not found: {full_patch_dir}")
            return {"placed": 0, "missing": len(patches)}

        # ── Build filename index: 6-digit patch id → [file paths] ────────────
        file_index: Dict[str, List[str]] = {}
        for fname in os.listdir(full_patch_dir):
            if not fname.lower().endswith(
                    (".png", ".tif", ".tiff", ".jpg", ".jpeg")):
                continue
            for pid0 in re.findall(r"(\d{6})", fname):
                file_index.setdefault(pid0, []).append(
                    os.path.join(full_patch_dir, fname))

        tag = ("he" if mode.lower() in ("he", "predicted_ihc")
               else biomarker.lower())

        # ── Allocate canvas ───────────────────────────────────────────────────
        if is_overlapping:
            canvas = np.zeros((h, w, 3), dtype=np.float32)
            counts = np.zeros((h, w, 1), dtype=np.float32)
        else:
            canvas = np.full((h, w, 3), 255, dtype=np.uint8)

        placed = missing = 0

        # ── Fill canvas ───────────────────────────────────────────────────────
        for p in tqdm(patches, desc=f"Assembling [{mode}]"):
            coords = p.get("coordinates")
            pid    = p.get("id")
            if coords is None or pid is None:
                continue
            x, y = int(coords[0]), int(coords[1])

            candidates = file_index.get(pid, [])
            if not candidates:
                candidates = sorted(
                    g for g in glob.glob(
                        os.path.join(full_patch_dir, f"*{pid}*"))
                    if g.lower().endswith(
                        (".png", ".tif", ".tiff", ".jpg", ".jpeg"))
                )
            if not candidates:
                tqdm.write(f"[WARN] Missing patch {pid}")
                missing += 1
                continue

            if len(candidates) == 1:
                chosen = candidates[0]
            else:
                chosen = next(
                    (c for c in candidates
                     if case_id.lower() in os.path.basename(c).lower()
                     or tag in os.path.basename(c).lower()),
                    candidates[0],
                )

            try:
                with Image.open(chosen) as img:
                    arr = np.array(img.convert("RGB"))
                ph, pw = arr.shape[:2]
                if is_overlapping:
                    canvas[y:y+ph, x:x+pw] += arr.astype(np.float32)
                    counts [y:y+ph, x:x+pw] += 1.0
                else:
                    canvas[y:y+ph, x:x+pw] = arr
                placed += 1
            except Exception as e:
                tqdm.write(f"[WARN] Cannot open {chosen}: {e}")
                missing += 1

        # ── Finalise array ────────────────────────────────────────────────────
        if is_overlapping:
            counts[counts == 0] = 1.0
            final_arr = (canvas / counts).clip(0, 255).astype(np.uint8)
        else:
            final_arr = canvas

        # ── Pyramidal TIFF via pyvips ─────────────────────────────────────────
        # pyvips.Image.new_from_memory wraps the numpy buffer with zero-copy.
        # tiffsave with pyramid=True writes all zoom levels in one pass.
        print(f"[INFO] Writing pyramidal TIFF → {final_save_path}")
        h_out, w_out = final_arr.shape[:2]
        vips_img = pyvips.Image.new_from_memory(
            final_arr.tobytes(), w_out, h_out, 3, "uchar"
        )
        vips_img.tiffsave(
            final_save_path,
            tile        = True,
            tile_width  = 512,
            tile_height = 512,
            pyramid     = True,
            compression = "lzw",
            Q           = 99,
            # bigtiff   = True,   # uncomment for output files > 4 GB
        )

        print(f"[OK] Saved: {final_save_path}  "
              f"(placed={placed}, missing={missing})")
        return {"placed": placed, "missing": missing}

    # ── Batch run ──────────────────────────────────────────────────────────────
    def run(self):
        """Extract patches for every H&E/IHC case found under the configured roots.

        The main batch entry point. For each H&E slide discovered by
        :meth:`_scan_he_cases`, attempts to locate its matching aligned
        IHC slide via :meth:`_find_aligned_ihc`; cases without a match
        are skipped (not treated as fatal errors, since a partially
        processed/aligned dataset is common). For each matched pair,
        delegates the actual patch extraction to
        :meth:`extract_from_case`.

        Returns
        -------
        None
            Progress and a final summary line
            (``processed``/``skipped`` counts) are printed; nothing is
            returned. If :meth:`_scan_he_cases` finds no H&E files at
            all, an error is printed and the method returns immediately
            without attempting any extraction.

        Notes
        -----
        Iterates cases with a :mod:`tqdm` progress bar
        (``desc="Processing Cases"``). Per-case status (skip/info
        messages) is written via ``tqdm.write`` rather than plain
        ``print`` so it doesn't corrupt the progress bar's rendering.
        """
        he_cases = self._scan_he_cases()
        if not he_cases:
            print("[ERROR] No HE files found. Check he_root and biomarker_folders.")
            return
        print(f"[INFO] Found {len(he_cases)} HE case(s) across {self.biomarker_folders}\n")
        skipped = processed = 0
        for sample_id, biomarker, he_path in tqdm(he_cases,
                                                   desc="Processing Cases",
                                                   unit="case"):
            aligned_ihc = self._find_aligned_ihc(sample_id, biomarker)
            case_id     = f"{sample_id}_{biomarker}"
            if aligned_ihc is None:
                tqdm.write(f"[SKIP] {case_id}: aligned IHC not found")
                skipped += 1
                continue
            tqdm.write(f"[INFO] {case_id}: IHC → {os.path.basename(aligned_ihc)}")
            self.extract_from_case(
                case_id      = case_id,
                hne_path     = he_path,
                marker_files = {biomarker.lower(): aligned_ihc},
            )
            processed += 1
        print(f"\n[DONE] Processed: {processed}  |  Skipped: {skipped}")


# ══════════════════════════════════════════════════════════════════════════════
# Config-driven patch extraction (generalized reference/target channel naming)
# ══════════════════════════════════════════════════════════════════════════════

#: Default regex for matching reference-channel filenames when
#: :class:`PatchExtractionConfig` is constructed without an explicit
#: ``he_filename_pattern``. Matches ``Sample_0001_he.tif``/``.tiff`` style
#: names, mirroring :class:`ReversiblePatchExtractor`'s hardcoded convention
#: — but here it's only the *default*, and any regex defining a
#: ``sample_id`` named group can be substituted.
DEFAULT_REFERENCE_FILENAME_PATTERN: str = r"^(?P<sample_id>[A-Za-z0-9]+)_he\.tiff?$"

@dataclass
class PatchExtractionConfig:
    """Configuration for the generalized sliding-window patch extraction pipeline.

    Unlike :class:`ReversiblePatchExtractor` (which hardcodes a
    ``Sample_NNNN_he.tif`` naming convention and fixed "he"/"ihc" channel
    labels), this config makes both the reference-channel filename
    pattern and the reference/target channel names caller-supplied — so
    the same pipeline works whether your anchor channel is literally
    H&E, or any other reference stain (e.g. a marker like ``"cd31"``
    used as the registration anchor, as in the Quickstart example
    below).

    Parameters
    ----------
    he_dir : str
        Root directory to search **recursively** for reference-channel
        whole-slide files. Every file whose name matches
        ``he_filename_pattern`` anywhere under this tree is treated as
        one case's reference channel, regardless of which subdirectory
        it's actually in.
    aligned_dir : str
        Root directory containing aligned target-channel files, expected
        to be organised as
        ``aligned_dir/<biomarker>/<sample_id>_<he_channel_name>/*.ome.tif*``
        for each biomarker in ``biomarker_folders`` — the same directory
        convention :class:`ReversiblePatchExtractor` uses, just
        parameterised by ``he_channel_name`` instead of a hardcoded
        ``"he"``.
    output_dir : str
        Root directory patches and per-case JSON metadata are written
        under. Created if it doesn't already exist.
    biomarker_folders : list of str
        Which biomarker subfolders under ``aligned_dir`` to look for an
        aligned target-channel match in, for every discovered reference
        file. Must be non-empty — there is deliberately no default list,
        so no specific biomarkers are assumed.
    he_filename_pattern : str, optional
        Regular expression used to identify reference-channel files and
        extract each one's sample identifier. Must define a named group
        called ``sample_id``. Defaults to
        :data:`DEFAULT_REFERENCE_FILENAME_PATTERN`. Matching is
        case-insensitive and applied to the filename only (not the full
        path) via :func:`re.match` (i.e. anchored at the start of the
        filename; use ``$`` in your pattern to anchor the end too, as
        the default does).
    he_channel_name : str, optional
        Label for the reference channel, used both to build the expected
        aligned-target subdirectory name
        (``<sample_id>_<he_channel_name>/``) and as the filename/metadata
        key for saved reference patches. Defaults to ``"he"``. Despite
        the field name (kept for continuity with
        ``ReversiblePatchExtractor``), this does not have to be H&E —
        it's whatever channel your slides were registered against.
    ihc_channel_name : str, optional
        Label for the target channel, used as the filename/metadata key
        for saved target patches. Defaults to ``"ihc"``. Like
        ``he_channel_name``, this can be any channel/biomarker label.
    patch_size : int, optional
        Edge length, in pixels, of each square patch. Defaults to
        ``256``.
    stride : int, optional
        Sliding-window step size, in pixels. Defaults to ``None``, which
        resolves to ``patch_size`` (non-overlapping patches) in
        :meth:`__post_init__`.
    tissue_threshold : float, optional
        Minimum fraction of non-background pixels (same brightness-based
        heuristic as :class:`ReversiblePatchExtractor`'s tissue gate) for
        a patch to be kept. Must be in ``[0, 1]``. Defaults to ``0.9``.
    max_workers : int, optional
        Number of cases to process concurrently. ``1`` (the default)
        processes cases sequentially in the calling thread; values
        greater than ``1`` use a :class:`concurrent.futures.ThreadPoolExecutor`.
        See :func:`run_patch_extraction`'s Notes for why threads rather
        than processes.

    Raises
    ------
    ValueError
        Raised by :meth:`__post_init__` if any field fails validation —
        see that method for the exact checks.
    """
    he_dir:              str
    aligned_dir:          str
    output_dir:           str
    biomarker_folders:    List[str]
    he_filename_pattern:  str = DEFAULT_REFERENCE_FILENAME_PATTERN
    he_channel_name:      str = "he"
    ihc_channel_name:     str = "ihc"
    patch_size:           int = 256
    stride:               Optional[int] = None
    tissue_threshold:     float = 0.9
    max_workers:          int = 1
    target_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    reference_source_magnification: Optional[float] = None
    target_source_magnification: Optional[float] = None
    dimension_tolerance: float = 0.01

    def __post_init__(self) -> None:
        """Validate fields and resolve ``stride``'s default immediately after construction.

        Raises
        ------
        ValueError
            If ``biomarker_folders`` is empty; if ``patch_size`` or the
            (possibly-defaulted) ``stride`` is not strictly positive; if
            ``tissue_threshold`` is outside ``[0, 1]``; if
            ``max_workers`` is less than 1; or if ``he_filename_pattern``
            is not a valid regex or does not define a ``sample_id``
            named group.

        Notes
        -----
        When ``stride`` is left as ``None`` (its default), it is set
        here to ``self.patch_size`` — i.e. non-overlapping patches —
        exactly once, so downstream code can always treat ``self.stride``
        as a concrete ``int``.
        """
        if not self.biomarker_folders:
            raise ValueError("biomarker_folders must be a non-empty list.")
        if self.patch_size <= 0:
            raise ValueError(f"patch_size must be > 0; got {self.patch_size}")
        if self.stride is None:
            self.stride = self.patch_size
        if self.stride <= 0:
            raise ValueError(f"stride must be > 0; got {self.stride}")
        if not (0.0 <= self.tissue_threshold <= 1.0):
            raise ValueError(f"tissue_threshold must be in [0, 1]; got {self.tissue_threshold}")
        if self.max_workers < 1:
            raise ValueError(f"max_workers must be >= 1; got {self.max_workers}")
        if self.target_magnification <= 0:
            raise ValueError("target_magnification must be > 0")
        for name, value in (
            ("reference_source_magnification", self.reference_source_magnification),
            ("target_source_magnification", self.target_source_magnification),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be > 0 when supplied")
        if not (0.0 <= self.dimension_tolerance <= 1.0):
            raise ValueError("dimension_tolerance must be in [0, 1]")
        try:
            compiled = re.compile(self.he_filename_pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"he_filename_pattern is not a valid regex: {e}") from e
        if "sample_id" not in compiled.groupindex:
            raise ValueError(
                f"he_filename_pattern must define named group 'sample_id'. "
                f"Pattern: {self.he_filename_pattern!r}"
            )


def _discover_reference_files(he_dir: str, pattern: "re.Pattern") -> List[Tuple[str, str]]:
    """Recursively find reference-channel files matching ``pattern`` under ``he_dir``.

    Parameters
    ----------
    he_dir : str
        Root directory to walk recursively via :func:`os.walk`.
    pattern : re.Pattern
        Compiled regex (case-insensitive) defining a ``sample_id`` named
        group, matched against each filename via :meth:`re.Pattern.match`
        (basename only, not the full path).

    Returns
    -------
    list of tuple of (str, str)
        One ``(sample_id, full_path)`` tuple per matched file, sorted by
        ``sample_id``. Empty if ``he_dir`` doesn't exist or contains no
        matches.
    """
    out: List[Tuple[str, str]] = []
    for root, _dirs, files in os.walk(he_dir):
        for fn in files:
            m = pattern.match(fn)
            if m:
                out.append((m.group("sample_id"), os.path.join(root, fn)))
    return sorted(out, key=lambda x: x[0])


def _find_aligned_target(aligned_dir: str, biomarker: str,
                         sample_id: str, he_channel_name: str) -> Optional[str]:
    """Locate the aligned target-channel OME-TIFF for a sample and biomarker.

    Parameterised counterpart of
    :meth:`ReversiblePatchExtractor._find_aligned_ihc` — identical
    directory-search and disambiguation logic, just with
    ``he_channel_name`` substituted for the hardcoded ``"he"`` suffix
    used there.

    Parameters
    ----------
    aligned_dir : str
        Root directory containing aligned target-channel files.
    biomarker : str
        Biomarker subfolder name under ``aligned_dir``.
    sample_id : str
        Sample identifier, as extracted by
        :func:`_discover_reference_files`.
    he_channel_name : str
        Reference-channel label used to build the expected case
        directory name, ``<sample_id>_<he_channel_name>``.

    Returns
    -------
    str or None
        Full path to the resolved aligned target file, or ``None`` if
        the expected case directory doesn't exist or contains no
        ``*.ome.tif*`` files.

    Notes
    -----
    If multiple ``*.ome.tif*`` files exist in the case directory,
    disambiguation is attempted by preferring a filename containing (in
    order) the lowercased biomarker name, then ``"ihc"``, then
    ``"aligned"``. If ambiguity remains, the first match alphabetically
    is used as a last resort rather than failing the whole run.
    """
    case_dir = os.path.join(aligned_dir, biomarker, f"{sample_id}_{he_channel_name}")
    if not os.path.isdir(case_dir):
        return None
    hits = sorted(glob.glob(os.path.join(case_dir, "*.ome.tif*")))
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    for kw in [biomarker.lower(), "ihc", "aligned"]:
        preferred = [h for h in hits if kw in os.path.basename(h).lower()]
        if len(preferred) == 1:
            return preferred[0]
    return hits[0]


def _patch_is_tissue(image_pil: "Image.Image", tissue_threshold: float) -> bool:
    """Decide whether a patch contains enough tissue to keep.

    Same brightness-based heuristic as
    :meth:`ReversiblePatchExtractor._is_tissue`, factored out as a
    module-level function so it can be used by both the sequential and
    thread-pool code paths in :func:`run_patch_extraction` without
    depending on a class instance.

    Parameters
    ----------
    image_pil : PIL.Image.Image
        The patch to test (any PIL mode; converted to ``"L"`` grayscale
        internally).
    tissue_threshold : float
        Minimum fraction of pixels darker than 235 (out of 255) for the
        patch to count as tissue.

    Returns
    -------
    bool
        ``True`` if the fraction of non-background pixels is at least
        ``tissue_threshold``; ``False`` otherwise.
    """
    return float(np.mean(np.array(image_pil.convert("L")) < 235)) >= tissue_threshold


def _extract_case_patches(case_id: str, reference_path: str, target_path: str,
                          biomarker: str, cfg: PatchExtractionConfig) -> Dict[str, Any]:
    """Run sliding-window extraction for a single reference/target case.

    Parameters
    ----------
    case_id : str
        Identifier for this case, used in output filenames (typically
        ``f"{sample_id}_{biomarker}"``).
    reference_path : str
        Path to the reference-channel whole-slide file.
    target_path : str
        Path to the aligned target-channel whole-slide file.
    biomarker : str
        Biomarker label for this case, used to build the output
        directory path.
    cfg : PatchExtractionConfig
        Supplies ``patch_size``, ``stride``, ``tissue_threshold``,
        ``he_channel_name``, ``ihc_channel_name``, and ``output_dir``.

    Returns
    -------
    dict
        ``{"case_id": case_id, "status": "processed", "n_patches": int}``.

    Notes
    -----
    Mirrors :meth:`ReversiblePatchExtractor.extract_from_case`'s sliding
    window / tissue-gate / save-and-record-metadata logic, generalized
    to use ``cfg.he_channel_name``/``cfg.ihc_channel_name`` as both the
    output subdirectory names and the metadata keys, instead of the
    hardcoded ``"he"``/``"ihc"``. Reads patches at pyramid level 0 (full
    resolution). Writes one PNG per kept patch for each of the two
    channels, plus a single ``{case_id}_metadata.json`` recording every
    kept patch's coordinates, size, and output paths.

    This function is called both from a sequential loop and from worker
    threads in a :class:`concurrent.futures.ThreadPoolExecutor` (see
    :func:`run_patch_extraction`) — it opens and closes its own
    :class:`_SlideReader` instances rather than sharing any, so it is
    safe to run concurrently for different cases.
    """
    ref_reader = _SlideReader(reference_path)
    target_reader = _SlideReader(target_path)
    try:
        ref_plan = ref_reader.configure_magnification(
            cfg.target_magnification, cfg.reference_source_magnification
        )
        target_plan = target_reader.configure_magnification(
            cfg.target_magnification, cfg.target_source_magnification
        )
        w, h = ref_reader.target_dimensions
        target_w, target_h = target_reader.target_dimensions
        relative_error = max(abs(target_w - w) / w, abs(target_h - h) / h)
        if relative_error > cfg.dimension_tolerance:
            raise ValueError(
                f"Reference and moving slides differ at {cfg.target_magnification:g}x: "
                f"{w}x{h} versus {target_w}x{target_h} "
                f"(tolerance={cfg.dimension_tolerance:.1%})."
            )

        case_dir = OutputLayout(cfg.output_dir).item_dir("patch_extraction", case_id)

        metadata: Dict[str, Any] = {
            "case_id": case_id,
            "dimensions": (w, h),
            "patch_size": cfg.patch_size,
            "stride": cfg.stride,
            "target_magnification": cfg.target_magnification,
            "reference_base_magnification": ref_plan.base_magnification,
            "reference_read_level": ref_plan.level,
            "target_base_magnification": target_plan.base_magnification,
            "target_read_level": target_plan.level,
            "reference_channel": cfg.he_channel_name,
            "target_channel": cfg.ihc_channel_name,
            "extraction_mode": "sliding",
            "patches": [],
        }
        idx = 1
        for y in range(0, h, cfg.stride):
            for x in range(0, w, cfg.stride):
                tw = min(cfg.patch_size, w - x)
                th = min(cfg.patch_size, h - y)
                ref_p = ref_reader.read_at_magnification((x, y), (tw, th)).convert("RGB")

                if _patch_is_tissue(ref_p, cfg.tissue_threshold):
                    pid = f"{idx:06d}"
                    rp = case_dir / f"{case_id}_{cfg.he_channel_name}_patch_{pid}.png"
                    ref_p.save(rp, compression=None)

                    tgt_p = target_reader.read_at_magnification((x, y), (tw, th)).convert("RGB")
                    tp = case_dir / f"{case_id}_{cfg.ihc_channel_name}_patch_{pid}.png"
                    tgt_p.save(tp, compression=None)
                    tgt_p.close()

                    metadata["patches"].append({
                        "id": pid,
                        "coordinates": (int(x), int(y)),
                        "size": (int(tw), int(th)),
                        f"{cfg.he_channel_name}_path": str(rp),
                        f"{cfg.ihc_channel_name}_path": str(tp),
                    })
                    idx += 1

                ref_p.close()

        meta_path = case_dir / f"{case_id}_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return {"case_id": case_id, "status": "processed", "n_patches": idx - 1}
    finally:
        ref_reader.close()
        target_reader.close()


def run_patch_extraction(cfg: PatchExtractionConfig) -> Dict[str, Any]:
    """Run the generalized, config-driven sliding-window patch extraction pipeline.

    For every reference-channel file discovered under ``cfg.he_dir``
    (matching ``cfg.he_filename_pattern``), and for every biomarker in
    ``cfg.biomarker_folders``, attempts to locate the corresponding
    aligned target-channel file under ``cfg.aligned_dir``. Cases without
    a match are recorded as skipped rather than treated as fatal errors,
    since a partially processed/aligned dataset is common. Matched cases
    are extracted via :func:`_extract_case_patches`, either sequentially
    or concurrently depending on ``cfg.max_workers``.

    Parameters
    ----------
    cfg : PatchExtractionConfig
        Fully validated configuration (validation happens in
        :meth:`PatchExtractionConfig.__post_init__` at construction
        time, not here).

    Returns
    -------
    dict
        ``{"processed": int, "skipped": int, "cases": list of dict}``
        where ``"cases"`` contains one entry per attempted case — either
        ``{"case_id", "status": "processed", "n_patches"}`` or
        ``{"case_id", "status": "skipped"|"failed", "reason"}``.

    Notes
    -----
    **Parallelism.** When ``cfg.max_workers > 1``, cases are submitted to
    a :class:`concurrent.futures.ThreadPoolExecutor`. Threads (not
    processes) are used deliberately: each case's work is dominated by
    I/O (OpenSlide region reads, PNG writes) and NumPy/Pillow operations
    that release the GIL, so threads capture most of the available
    concurrency without the pickling overhead and per-worker OpenSlide
    handle duplication that a process pool would require. If your
    workload is instead CPU-bound (e.g. very large patches with heavy
    NumPy post-processing), you may see limited additional speedup past
    a few workers due to the GIL — profile before setting
    ``max_workers`` very high.

    **No global progress bar** is shown for the parallel path (individual
    cases still log their own completion via ``print()``) — this keeps
    the output readable when multiple cases interleave, at the cost of
    the single unified :mod:`tqdm` bar the sequential path provides.
    """
    pattern = re.compile(cfg.he_filename_pattern, re.IGNORECASE)
    reference_files = _discover_reference_files(cfg.he_dir, pattern)

    if not reference_files:
        print(f"[ERROR] No reference-channel files found under {cfg.he_dir} "
              f"matching pattern: {cfg.he_filename_pattern}")
        return {"processed": 0, "skipped": 0, "cases": []}

    print(f"[INFO] Found {len(reference_files)} reference file(s); "
          f"checking {len(cfg.biomarker_folders)} biomarker(s) each.\n")

    to_process: List[Tuple[str, str, str, str]] = []
    results: List[Dict[str, Any]] = []

    for sample_id, ref_path in reference_files:
        for biomarker in cfg.biomarker_folders:
            case_id = f"{sample_id}_{biomarker}"
            target_path = _find_aligned_target(
                cfg.aligned_dir, biomarker, sample_id, cfg.he_channel_name
            )
            if target_path is None:
                print(f"[SKIP] {case_id}: aligned target not found")
                results.append({"case_id": case_id, "status": "skipped",
                                "reason": "aligned target not found"})
                continue
            to_process.append((case_id, ref_path, target_path, biomarker))

    if cfg.max_workers > 1 and len(to_process) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
            futures = {
                pool.submit(_extract_case_patches, case_id, ref_path, target_path,
                           biomarker, cfg): case_id
                for case_id, ref_path, target_path, biomarker in to_process
            }
            for future in concurrent.futures.as_completed(futures):
                case_id = futures[future]
                try:
                    result = future.result()
                    print(f"[OK] {result['case_id']}: {result['n_patches']} patches saved")
                    results.append(result)
                except Exception as e:
                    print(f"[ERROR] {case_id}: {e}")
                    results.append({"case_id": case_id, "status": "failed", "reason": str(e)})
    else:
        for case_id, ref_path, target_path, biomarker in tqdm(
            to_process, desc="Processing Cases", unit="case"
        ):
            try:
                result = _extract_case_patches(case_id, ref_path, target_path, biomarker, cfg)
                tqdm.write(f"[OK] {result['case_id']}: {result['n_patches']} patches saved")
                results.append(result)
            except Exception as e:
                tqdm.write(f"[ERROR] {case_id}: {e}")
                results.append({"case_id": case_id, "status": "failed", "reason": str(e)})

    processed = sum(1 for r in results if r["status"] == "processed")
    skipped   = sum(1 for r in results if r["status"] in ("skipped", "failed"))
    print(f"\n[DONE] Processed: {processed}  |  Skipped/Failed: {skipped}")

    return {"processed": processed, "skipped": skipped, "cases": results}
