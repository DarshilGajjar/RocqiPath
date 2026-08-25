"""Legacy reversible sliding-window patch extractor."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tqdm.auto import tqdm

from rocqipath.core.magnification import DEFAULT_TARGET_MAGNIFICATION
from rocqipath.core.output import OutputLayout
from rocqipath.core.slide import SlideReader as _SlideReader
from rocqipath.core.tissue import pil_is_tissue as _pil_is_tissue
from rocqipath.extraction.reconstruction import (
    _assemble_canvas,
    _finalize_canvas,
    _index_patch_files,
    _load_metadata,
    _patch_directory,
    _save_pyramid,
)
from rocqipath.utils.discovery import find_aligned_wsi


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
        self.cfg = cfg
        self.patch_size = int(cfg.get("patch_size", 256))
        self.stride = int(cfg.get("stride", self.patch_size))

        self.output_dir = os.path.abspath(cfg.get("output_dir", "./output"))
        self.he_root = os.path.abspath(cfg["he_root"])
        self.aligned_root = os.path.abspath(cfg["aligned_root"])
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
            print(
                f"[DEBUG] HE biomarker folders: "
                f"{[d for d in os.listdir(self.he_root) if os.path.isdir(os.path.join(self.he_root, d))]}"
            )
        if os.path.isdir(self.aligned_root):
            print(
                f"[DEBUG] Aligned biomarker folders: "
                f"{[d for d in os.listdir(self.aligned_root) if os.path.isdir(os.path.join(self.aligned_root, d))]}"
            )

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
        return _pil_is_tissue(
            image_pil,
            threshold=self.tissue_threshold,
            intensity_threshold=235,
        )

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
                    out.append((m.group(1), biomarker.upper(), os.path.join(bio_he_dir, fn)))
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

        def _report(event: str, case_dir: Path, hits: list[Path]) -> None:
            if event == "missing_directory":
                print(f"[DEBUG] Case folder not found: {case_dir}")
            elif event == "no_matches":
                print(f"[DEBUG] No .ome.tif* in: {case_dir}  |  contents: {os.listdir(case_dir)}")
            elif event == "ambiguous_fallback":
                print(f"[WARN] Multiple OME-TIFFs; using: {hits[0].name}")

        return find_aligned_wsi(
            self.aligned_root,
            biomarker,
            sample_id,
            "he",
            priority_keywords=(biomarker.lower(), "ihc", "aligned"),
            sort_mode="lexical",
            resolve=False,
            on_event=_report,
        )

    # ── Patch extraction ───────────────────────────────────────────────────────
    def extract_from_case(self, case_id: str, hne_path: str, marker_files: Dict[str, str]):
        """Sliding-window extraction across the whole slide."""
        os_hne = _SlideReader(hne_path)
        os_markers = {m: _SlideReader(p) for m, p in marker_files.items()}
        os_hne.configure_magnification(
            self.target_magnification, self.reference_source_magnification
        )
        for reader in os_markers.values():
            reader.configure_magnification(
                self.target_magnification, self.target_source_magnification
            )
        w, h = os_hne.target_dimensions
        case_dir = OutputLayout(self.output_dir).item_dir("patch_extraction", case_id)

        metadata = {
            "case_id": case_id,
            "dimensions": (w, h),
            "patch_size": self.patch_size,
            "stride": self.stride,
            "target_magnification": self.target_magnification,
            "extraction_mode": "sliding",
            "patches": [],
        }
        idx = 1
        tiles_x = (w + self.stride - 1) // self.stride
        tiles_y = (h + self.stride - 1) // self.stride

        with tqdm(
            total=tiles_x * tiles_y, desc=f"   -> {case_id}", leave=False, unit="patch"
        ) as pbar:
            for y in range(0, h, self.stride):
                for x in range(0, w, self.stride):
                    tw = min(self.patch_size, w - x)
                    th = min(self.patch_size, h - y)
                    hne_p = os_hne.read_at_magnification((x, y), (tw, th)).convert("RGB")

                    if self._is_tissue(hne_p):
                        pid = f"{idx:06d}"
                        hp = case_dir / f"{case_id}_he_patch_{pid}.png"
                        hne_p.save(hp, compression=None)
                        info = {
                            "id": pid,
                            "coordinates": (int(x), int(y)),
                            "size": (int(tw), int(th)),
                            "he_path": str(hp),
                        }
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

    def reconstruct_wsi(
        self,
        case_id: str,
        biomarker: str,
        output_path: str,
        mode: str = "he",
        split: str = "test",
    ) -> dict:
        """Reconstruct extracted patches as a pyramidal whole-slide TIFF."""
        del split
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
        for sample_id, biomarker, he_path in tqdm(he_cases, desc="Processing Cases", unit="case"):
            aligned_ihc = self._find_aligned_ihc(sample_id, biomarker)
            case_id = f"{sample_id}_{biomarker}"
            if aligned_ihc is None:
                tqdm.write(f"[SKIP] {case_id}: aligned IHC not found")
                skipped += 1
                continue
            tqdm.write(f"[INFO] {case_id}: IHC → {os.path.basename(aligned_ihc)}")
            self.extract_from_case(
                case_id=case_id,
                hne_path=he_path,
                marker_files={biomarker.lower(): aligned_ihc},
            )
            processed += 1
        print(f"\n[DONE] Processed: {processed}  |  Skipped: {skipped}")
