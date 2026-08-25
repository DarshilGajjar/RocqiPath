"""Count DAB-positive cells in whole-slide images.

Use an HSV brown-colour gate plus OTSU thresholding on the inverted Value
channel within that gate. Applies
to any DAB-chromogen IHC marker your dataset targets — the algorithm
itself is marker-agnostic.

Algorithm (per patch)
---------------------
1.  Brown colour gate in HSV:
        Hue  ∈ [5, 20]   (orange-brown — excludes haematoxylin H ≈ 110-140)
        Sat  ≥ 30        (excludes pale background / grey)
        Val  ≤ 220       (excludes white background)
2.  Invert the Value channel so dark-brown cells become bright.
3.  OTSU threshold on the inverted-Value pixels that fall inside the brown
    gate — computed SEPARATELY for GT and Prediction (user request).
4.  Connected-component labelling + min/max area filter.

Outputs
-------
  • JSON  — total counts, density (cells/mm²), positivity %, tissue area
  • Excel — per-patch GT vs Pred counts, Otsu thresholds, difference, summary stats
  • PNG   — dark-themed 2×3 panel per patch: Original | Brown gate | Binary overlay

References
----------
  Galon J. et al., Science 2006  (cells/mm² metric)
  Ruifrok & Johnston 2001        (H-DAB colour reference)
"""

import json
import warnings
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from skimage import filters, measure, morphology
from tqdm.auto import tqdm
from rocqipath.config import CellCountingConfig
from rocqipath.core.output import OutputLayout
from rocqipath.core.slide import SlideReader as _SlideReader
from rocqipath.core.tissue import is_tissue as _shared_is_tissue
from rocqipath.core.tissue import tissue_mask as _shared_tissue_mask
from rocqipath.analysis.reporting import _save_comparison_plot, _write_excel

try:
    import openslide
except ImportError:  # optional; PIL-backed synthetic/ordinary TIFFs still work
    openslide = None  # type: ignore[assignment]

warnings.filterwarnings("ignore")

# ── Aperio standard MPP (used when metadata is unavailable) ──────────────────
_APERIO_MPP = 0.2528  # µm/px at 40×, Aperio AT2

# ── WSI extensions ────────────────────────────────────────────────────────────
WSI_EXTENSIONS = frozenset(
    {".svs", ".tif", ".tiff", ".ome.tif", ".ome.tiff", ".ndpi", ".scn", ".mrxs", ".vms", ".vmu"}
)


# ── Slide reader with PIL fallback ────────────────────────────────────────────
# ── Excel output ──────────────────────────────────────────────────────────────


# ── Main class ────────────────────────────────────────────────────────────────
class PositiveCellCounter:
    """Count DAB-positive cells across whole-slide images.

    Use an HSV brown-colour gate combined with per-image OTSU thresholding.
    This works with any DAB-chromogen IHC marker — the detection method
    itself has no notion of which biomarker produced the brown signal,
    only that it is brown. See the module docstring for the full
    algorithm description and references.

    Typical usage
    -------------
    ::

        counter = PositiveCellCounter({
            "patch_size":   512,
            "magnification": 2,
            "output_dir":   "./results/cell_counts",
        })
        result = counter.count_slide("./slide_01.svs")

    Parameters (cfg dict)
    ---------------------
    patch_size        : tile size in pixels at the chosen magnification (default 512)
    tissue_threshold  : minimum tissue fraction per patch (default 0.10)
    target_magnification : physical analysis zoom — default 20x
    output_dir        : root output folder
    min_cell_area     : minimum cell area in px² (default 50)
    max_cell_area     : maximum cell area in px², None = no upper bound
    """

    def __init__(self, cfg: CellCountingConfig | dict):
        """Resolve configuration, create the output directory, and print a summary.

        Parameters
        ----------
        cfg : dict
            Configuration dict. All keys are optional:

            - ``"patch_size"`` (int) — tile edge length in pixels at the
              chosen magnification. Defaults to ``512``.
            - ``"tissue_threshold"`` (float) — minimum fraction of
              non-background pixels (see :meth:`_is_tissue`) for a patch
              to be processed at all. Defaults to ``0.10``.
            - ``"target_magnification"`` (float) — exact physical zoom for
              analysis. Defaults to ``20.0``. The legacy ``"magnification"``
              key is accepted as a physical-value alias.
            - ``"output_dir"`` (str) — root directory for results.
              Defaults to ``"./cell_count_output"``; created if it
              doesn't exist.
            - ``"min_cell_area"`` (int) — minimum connected-component
              area, in pixels², for a detected blob to count as a cell.
              Defaults to ``50``.
            - ``"max_cell_area"`` (int or None) — maximum connected-component
              area, in pixels². When omitted, empty, or ``0``, treated
              as "no upper bound" (``self.max_cell_area`` becomes
              ``None``).

        Notes
        -----
        Prints a startup summary (patch size, tissue threshold, cell
        area range, thresholding strategy) to stdout after resolving all
        fields.
        """
        resolved = cfg if isinstance(cfg, CellCountingConfig) else CellCountingConfig.from_dict(cfg)
        self.patch_size = resolved.patch_size
        self.tissue_threshold = resolved.tissue_threshold
        self.target_magnification = resolved.target_magnification
        self.source_magnification = resolved.source_magnification
        self.paired_source_magnification = resolved.paired_source_magnification
        self.output_dir = resolved.output_dir
        self.min_cell_area = resolved.min_cell_area
        self.max_cell_area = resolved.max_cell_area

        self.layout = OutputLayout(self.output_dir)
        self.layout.module_dir("cell_counting")
        _max_str = f"{self.max_cell_area}" if self.max_cell_area else "∞"
        print("[INFO] Positive Cell Counter (HSV brown gate + OTSU)")
        print(f"       Patch size       : {self.patch_size} px at {self.target_magnification:g}x")
        print(f"       Tissue threshold : {int(self.tissue_threshold * 100)}%")
        print(f"       Cell area range  : {self.min_cell_area} – {_max_str} px²")
        print("       Thresholding     : OTSU computed separately per image")

    # ── Tissue gate ───────────────────────────────────────────────────────────
    def _is_tissue(self, rgb: np.ndarray) -> bool:
        """Decide whether a patch contains enough tissue to bother counting cells.

        Parameters
        ----------
        rgb : numpy.ndarray
            An RGB patch array (any integer dtype; mean brightness is
            computed across the colour channels).

        Returns
        -------
        bool
            ``True`` if the fraction of pixels whose mean RGB value is
            below 235 (i.e. not near-white background) is at least
            ``self.tissue_threshold``; ``False`` otherwise, meaning the
            patch is mostly blank slide background.
        """
        return _shared_is_tissue(
            rgb,
            threshold=self.tissue_threshold,
            method="mean_intensity",
            intensity_threshold=235,
        )

    @staticmethod
    def _tissue_mask(rgb: np.ndarray) -> np.ndarray:
        """Return the per-pixel tissue mask used for both gating and area."""
        return _shared_tissue_mask(
            rgb,
            method="mean_intensity",
            intensity_threshold=235,
        )

    # ── MPP ───────────────────────────────────────────────────────────────────
    @staticmethod
    def _get_mpp(slide) -> Tuple[float, float]:
        """Read the microns-per-pixel (MPP) calibration from slide metadata.

        Parameters
        ----------
        slide : openslide.OpenSlide or similar
            An open slide handle exposing an OpenSlide-style
            ``.properties`` mapping.

        Returns
        -------
        tuple of (float, float)
            ``(mpp_x, mpp_y)`` read from the slide's
            ``openslide.mpp-x`` / ``openslide.mpp-y`` properties. Returns
            ``(0.0, 0.0)`` if the properties are missing or cannot be
            parsed as floats (caught via a broad ``except Exception``) —
            callers (e.g. :meth:`count_slide`) treat this as "MPP
            unavailable" and typically substitute a fallback constant
            (e.g. the Aperio standard) rather than failing outright.
        """
        try:
            props = slide.properties
            key_x = getattr(openslide, "PROPERTY_NAME_MPP_X", "openslide.mpp-x")
            key_y = getattr(openslide, "PROPERTY_NAME_MPP_Y", "openslide.mpp-y")
            return (float(props[key_x]), float(props[key_y]))
        except Exception:
            return 0.0, 0.0

    # ── Core counting: HSV brown gate + OTSU ─────────────────────────────────
    @staticmethod
    def _brown_mask(img_rgb: np.ndarray) -> np.ndarray:
        """Return a boolean mask for brown DAB-positive pixels.

        Hue ∈ [5, 20], Sat ≥ 30, Val ≤ 220  (OpenCV HSV: H ∈ [0,180]).
        Explicitly excludes haematoxylin blue (H ≈ 110-140) and background.
        """
        hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
        H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        return (H >= 5) & (H <= 20) & (S >= 30) & (V <= 220)

    def _count_patch(self, img_rgb: np.ndarray, threshold: Optional[float] = None) -> Tuple:
        """
        Count positive cells in one RGB patch using HSV brown gate + OTSU.

        Parameters
        ----------
        img_rgb   : H × W × 3 uint8 RGB array
        threshold : if None → compute OTSU from this patch's own brown pixels
                    if float → apply this fixed threshold (for shared-threshold mode)

        Returns
        -------
        count, binary_mask, brown_vis, threshold_used, labels
        """
        brown = self._brown_mask(img_rgb)
        empty = np.zeros(img_rgb.shape[:2], bool)

        if brown.sum() < 10:
            return 0, empty, img_rgb.copy(), 0.0, np.zeros(img_rgb.shape[:2], int)

        # Invert Value so dark-brown cells become bright
        hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
        inv_val = cv2.bitwise_not(hsv[..., 2])

        # OTSU on brown pixels only (or use supplied fixed threshold)
        if threshold is None:
            threshold = float(filters.threshold_otsu(inv_val[brown]))

        binary = (inv_val > threshold) & brown
        binary = morphology.remove_small_objects(binary, min_size=self.min_cell_area)
        binary = morphology.remove_small_holes(
            binary, area_threshold=max(1, self.min_cell_area // 2)
        )

        labels = measure.label(binary)
        regions = measure.regionprops(labels)
        max_a = self.max_cell_area or float("inf")
        valid = [r.label for r in regions if self.min_cell_area <= r.area <= max_a]
        binary = np.isin(labels, valid)
        labels = measure.label(binary)
        count = int(labels.max())

        # Visualisation: brown pixels in original colour, rest grey
        brown_vis = np.full_like(img_rgb, 210)
        brown_vis[brown] = img_rgb[brown]

        return count, binary, brown_vis, float(threshold), labels

    # ── Patch comparison plot ─────────────────────────────────────────────────

    # ── Single slide ──────────────────────────────────────────────────────────
    def count_slide(self, wsi_path: str, label: str = "Cell") -> dict:
        """Count DAB-positive cells across one whole-slide image.

        Parameters
        ----------
        wsi_path : str
            Input slide path. Patch coordinates are evaluated at
            ``target_magnification``.
        label : str, optional
            Human-readable marker label stored in the JSON result.

        Returns
        -------
        dict
            Total positive count, tissue area in square millimetres,
            density, tissue pixels, and effective micrometres per pixel.

        Notes
        -----
        Each tissue patch receives an independent Otsu threshold. Tissue
        area uses target-grid pixels and physical MPP metadata, falling
        back to the historical Aperio value when metadata is absent.
        """
        slide = _SlideReader(wsi_path)
        plan = slide.configure_magnification(self.target_magnification, self.source_magnification)
        w, h = slide.target_dimensions
        mpp_x, mpp_y = self._get_mpp(slide)
        slide_name = Path(wsi_path).stem

        print(f"[INFO] Slide       : {Path(wsi_path).name}")
        print(f"[INFO] Dimensions  : {w} × {h} px")
        if mpp_x:
            print(f"[INFO] Resolution  : {mpp_x:.4f} µm/px  (from metadata)")
            mpp_x *= plan.level0_per_target_pixel
            mpp_y *= plan.level0_per_target_pixel
        else:
            level0_mpp = _APERIO_MPP
            mpp_x = mpp_y = level0_mpp * plan.level0_per_target_pixel
            print(f"[WARN] MPP not in metadata — using {mpp_x:.4f} µm/px at target zoom")

        total_pos = tissue_px = 0
        tiles_x = (w + self.patch_size - 1) // self.patch_size
        tiles_y = (h + self.patch_size - 1) // self.patch_size

        with tqdm(total=tiles_x * tiles_y, desc=f"  {slide_name}", unit="patch") as pbar:
            for py in range(0, h, self.patch_size):
                for px in range(0, w, self.patch_size):
                    tw = min(self.patch_size, w - px)
                    th = min(self.patch_size, h - py)
                    patch = slide.read_at_magnification((px, py), (tw, th)).convert("RGB")
                    rgb = np.array(patch)
                    patch.close()

                    if self._is_tissue(rgb):
                        count, *_ = self._count_patch(rgb)  # own OTSU
                        total_pos += count
                        tissue_px += int(np.count_nonzero(self._tissue_mask(rgb)))
                    pbar.update(1)

        slide.close()

        px_mm2 = (mpp_x / 1000.0) * (mpp_y / 1000.0)
        tissue_area_mm2 = tissue_px * px_mm2
        density_per_mm2 = total_pos / tissue_area_mm2 if tissue_area_mm2 > 0 else 0.0

        print("\n[RESULT] ══════════════════════════════════")
        print(f"[RESULT]  DAB+ cells    : {total_pos:,}")
        print(f"[RESULT]  Tissue area   : {tissue_area_mm2:.3f} mm²")
        print(f"[RESULT]  Density       : {density_per_mm2:.1f} cells/mm²")
        print("[RESULT] ══════════════════════════════════")

        results = {
            "slide": Path(wsi_path).name,
            "label": label,
            "total_positive": int(total_pos),
            "tissue_area_mm2": round(tissue_area_mm2, 4),
            "density_per_mm2": round(density_per_mm2, 2),
            "tissue_pixels": int(tissue_px),
            "tissue_area_method": "pixel_mask",
            "mpp_x": mpp_x,
            "mpp_y": mpp_y,
        }
        out_dir = self.layout.item_dir("cell_counting", slide_name)
        json_path = out_dir / f"{slide_name}_cell_count_results.json"
        with open(json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"[INFO]  Saved → {json_path}")
        return results

    # ── GT vs Prediction pair ─────────────────────────────────────────────────

    def count_slide_pair(
        self,
        gt_path: str,
        pred_path: str,
        label: str = "Cell",
        save_plots: bool = True,
        max_plots: int = 10,
        dpi: int = 150,
    ) -> dict:
        """Compare DAB-positive counts in ground-truth and predicted slides."""
        import matplotlib

        matplotlib.use("Agg")

        gt_slide = _SlideReader(gt_path)
        pred_slide = _SlideReader(pred_path)
        gt_plan = gt_slide.configure_magnification(
            self.target_magnification, self.source_magnification
        )
        pred_slide.configure_magnification(
            self.target_magnification, self.paired_source_magnification
        )
        width, height = gt_slide.target_dimensions
        if pred_slide.target_dimensions != (width, height):
            raise ValueError(
                f"Slides differ at {self.target_magnification:g}x: "
                f"{width}x{height} vs "
                f"{pred_slide.target_dimensions[0]}x{pred_slide.target_dimensions[1]}"
            )
        mpp_x, mpp_y = self._get_mpp(gt_slide)

        print(f"[INFO] GT slide    : {Path(gt_path).name}")
        print(f"[INFO] Pred slide  : {Path(pred_path).name}")
        print(f"[INFO] Dimensions  : {width} × {height} px")
        if mpp_x:
            print(f"[INFO] Resolution  : {mpp_x:.4f} µm/px  (from metadata)")
            mpp_x *= gt_plan.level0_per_target_pixel
            mpp_y *= gt_plan.level0_per_target_pixel
        else:
            mpp_x = mpp_y = _APERIO_MPP * gt_plan.level0_per_target_pixel
            print(f"[WARN] MPP not in metadata — using {mpp_x:.4f} µm/px at target zoom")

        item_name = f"{Path(gt_path).stem}_vs_{Path(pred_path).stem}"
        out_dir = self.layout.item_dir("cell_counting", item_name)
        gt_total = pred_total = tissue_px = 0
        plots_saved = patch_idx = 0
        patch_results: List[dict] = []
        tiles_x = (width + self.patch_size - 1) // self.patch_size
        tiles_y = (height + self.patch_size - 1) // self.patch_size

        with tqdm(total=tiles_x * tiles_y, desc="  GT vs Pred", unit="patch") as pbar:
            for py in range(0, height, self.patch_size):
                for px in range(0, width, self.patch_size):
                    tile_width = min(self.patch_size, width - px)
                    tile_height = min(self.patch_size, height - py)
                    gt_patch = gt_slide.read_at_magnification(
                        (px, py), (tile_width, tile_height)
                    ).convert("RGB")
                    gt_rgb = np.array(gt_patch)
                    gt_patch.close()
                    if not self._is_tissue(gt_rgb):
                        pbar.update(1)
                        continue

                    patch_idx += 1
                    tissue_px += int(np.count_nonzero(self._tissue_mask(gt_rgb)))
                    pred_patch = pred_slide.read_at_magnification(
                        (px, py), (tile_width, tile_height)
                    ).convert("RGB")
                    pred_rgb = np.array(pred_patch)
                    pred_patch.close()
                    gt_result = self._count_patch(gt_rgb, threshold=None)
                    pred_result = self._count_patch(pred_rgb, threshold=None)
                    gt_count, _, _, gt_threshold, _ = gt_result
                    pred_count, _, _, pred_threshold, _ = pred_result
                    gt_total += gt_count
                    pred_total += pred_count
                    patch_results.append(
                        {
                            "patch_name": f"patch_{patch_idx:04d}",
                            "gt_count": gt_count,
                            "pred_count": pred_count,
                            "gt_threshold": round(gt_threshold, 1),
                            "pred_threshold": round(pred_threshold, 1),
                            "gt_path": str(gt_path),
                            "pred_path": str(pred_path),
                        }
                    )
                    if save_plots and plots_saved < max_plots:
                        filename = str(out_dir / f"patch_{patch_idx:04d}_x{px}_y{py}.png")
                        _save_comparison_plot(
                            gt_rgb,
                            gt_result,
                            pred_rgb,
                            pred_result,
                            patch_idx,
                            px,
                            py,
                            filename,
                            dpi=dpi,
                        )
                        plots_saved += 1
                        tqdm.write(
                            f"  [PLOT] {plots_saved}/{max_plots}  "
                            f"GT={gt_count} (θ={gt_threshold:.1f})  "
                            f"Pred={pred_count} (θ={pred_threshold:.1f})"
                        )
                    pbar.update(1)

        gt_slide.close()
        pred_slide.close()
        pixel_area_mm2 = (mpp_x / 1000.0) * (mpp_y / 1000.0)
        tissue_area_mm2 = tissue_px * pixel_area_mm2
        density_gt = gt_total / tissue_area_mm2 if tissue_area_mm2 > 0 else 0.0
        density_pred = pred_total / tissue_area_mm2 if tissue_area_mm2 > 0 else 0.0
        difference = pred_total - gt_total
        difference_percent = difference / gt_total * 100 if gt_total > 0 else float("nan")

        print("\n[RESULT] ══════════════════════════════════════════════")
        print(f"[RESULT]  Tissue patches    : {patch_idx}")
        print(f"[RESULT]  GT  DAB+ cells    : {gt_total:,}")
        print(f"[RESULT]  Pred DAB+ cells   : {pred_total:,}")
        print(f"[RESULT]  Δ absolute        : {difference:+,}")
        if gt_total > 0:
            print(f"[RESULT]  Δ relative        : {difference_percent:+.1f}%")
        print(f"[RESULT]  Tissue area       : {tissue_area_mm2:.3f} mm²")
        print(f"[RESULT]  GT  density       : {density_gt:.1f} cells/mm²")
        print(f"[RESULT]  Pred density      : {density_pred:.1f} cells/mm²")
        if save_plots:
            print(f"[RESULT]  Plots saved       : {plots_saved}  →  {out_dir}")
        print("[RESULT] ══════════════════════════════════════════════")

        summary = {
            "gt_slide": Path(gt_path).name,
            "pred_slide": Path(pred_path).name,
            "label": label,
            "gt_positive": int(gt_total),
            "pred_positive": int(pred_total),
            "diff_absolute": int(difference),
            "diff_pct": round(difference_percent, 2) if gt_total > 0 else None,
            "tissue_area_mm2": round(tissue_area_mm2, 4),
            "tissue_pixels": int(tissue_px),
            "tissue_area_method": "ground_truth_pixel_mask",
            "gt_density_per_mm2": round(density_gt, 2),
            "pred_density_per_mm2": round(density_pred, 2),
            "plots_saved": plots_saved,
            "thresholding": "independent_otsu_per_image",
        }
        json_path = out_dir / f"{Path(gt_path).stem}_vs_{Path(pred_path).stem}_results.json"
        with open(json_path, "w") as stream:
            json.dump(summary, stream, indent=2)
        print(f"[INFO]  JSON  → {json_path}")
        excel_path = out_dir / f"{Path(gt_path).stem}_vs_{Path(pred_path).stem}_counts.xlsx"
        _write_excel(patch_results, str(excel_path))
        return summary

    # ── Batch ─────────────────────────────────────────────────────────────────

    def count_batch(self, input_dir: str, label: str = "Cell") -> list:
        """Count every supported WSI in a directory."""
        slides = sorted(
            path
            for path in Path(input_dir).iterdir()
            if any(str(path).lower().endswith(extension) for extension in WSI_EXTENSIONS)
        )
        if not slides:
            print(f"[ERROR] No WSI files found in: {input_dir}")
            return []

        print(f"[INFO] Found {len(slides)} slide(s)")
        all_results = []
        for slide_path in slides:
            print(f"\n{'─' * 50}")
            try:
                all_results.append(self.count_slide(str(slide_path), label=label))
            except Exception as exc:
                print(f"[ERROR] {slide_path.name}: {exc}")

        if all_results:
            total = sum(result["total_positive"] for result in all_results)
            print("\n[BATCH] ══════════════════════════════════")
            print(f"[BATCH]  Slides  : {len(all_results)}")
            print(f"[BATCH]  Total   : {total:,} DAB+ cells")
            print("[BATCH] ══════════════════════════════════")
            output_dir = self.layout.module_dir("cell_counting")
            with open(output_dir / "batch_cell_count_results.json", "w") as stream:
                json.dump(all_results, stream, indent=2)

        return all_results
