"""Paired-slide and batch orchestration mixin for cell counting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import numpy as np
from tqdm.auto import tqdm

from rocqipath.analysis.reporting import _save_comparison_plot, _write_excel
from rocqipath.core.slide import SlideReader as _SlideReader

_APERIO_MPP = 0.2528
WSI_EXTENSIONS = frozenset(
    {".svs", ".tif", ".tiff", ".ome.tif", ".ome.tiff", ".ndpi", ".scn", ".mrxs", ".vms", ".vmu"}
)


class CellBatchMixin:
    """Provide paired-slide and directory-level counting workflows."""

    def count_slide_pair(
        self,
        gt_path: str,
        pred_path: str,
        label: str = "Cell",
        save_plots: bool = True,
        max_plots: int = 10,
        dpi: int = 150,
    ) -> dict:
        """Compare DAB-positive counts in ground-truth and predicted slides.

        Parameters
        ----------
        gt_path : str
            Ground-truth WSI path.
        pred_path : str
            Prediction WSI path aligned to the ground-truth coordinate space.
        label : str, optional
            Human-readable marker label stored in results.
        save_plots : bool, optional
            Save per-patch comparison figures.
        max_plots : int, optional
            Maximum number of comparison figures.
        dpi : int, optional
            Figure resolution in dots per inch.

        Returns
        -------
        dict
            Paired totals, absolute and relative difference, tissue area,
            density values, and plot count.

        Raises
        ------
        ValueError
            If the slides have different dimensions at target magnification.

        Notes
        -----
        Otsu thresholds are computed independently for ground truth and
        prediction. Tissue area is measured from the ground-truth mask.
        """
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
        w, h = gt_slide.target_dimensions
        if pred_slide.target_dimensions != (w, h):
            raise ValueError(
                f"Slides differ at {self.target_magnification:g}x: "
                f"{w}x{h} vs {pred_slide.target_dimensions[0]}x{pred_slide.target_dimensions[1]}"
            )
        mpp_x, mpp_y = self._get_mpp(gt_slide)

        print(f"[INFO] GT slide    : {Path(gt_path).name}")
        print(f"[INFO] Pred slide  : {Path(pred_path).name}")
        print(f"[INFO] Dimensions  : {w} × {h} px")
        if mpp_x:
            print(f"[INFO] Resolution  : {mpp_x:.4f} µm/px  (from metadata)")
            mpp_x *= gt_plan.level0_per_target_pixel
            mpp_y *= gt_plan.level0_per_target_pixel
        else:
            mpp_x = mpp_y = _APERIO_MPP * gt_plan.level0_per_target_pixel
            print(f"[WARN] MPP not in metadata — using {mpp_x:.4f} µm/px at target zoom")

        item_name = f"{Path(gt_path).stem}_vs_{Path(pred_path).stem}"
        out_dir = self.layout.item_dir("cell_counting", item_name)
        plots_dir = out_dir

        gt_total = pred_total = tissue_px = 0
        plots_saved = patch_idx = 0
        patch_results: List[dict] = []

        tiles_x = (w + self.patch_size - 1) // self.patch_size
        tiles_y = (h + self.patch_size - 1) // self.patch_size

        with tqdm(total=tiles_x * tiles_y, desc="  GT vs Pred", unit="patch") as pbar:
            for py in range(0, h, self.patch_size):
                for px in range(0, w, self.patch_size):
                    tw = min(self.patch_size, w - px)
                    th = min(self.patch_size, h - py)

                    gt_patch = gt_slide.read_at_magnification((px, py), (tw, th)).convert("RGB")
                    gt_rgb = np.array(gt_patch)
                    gt_patch.close()

                    if not self._is_tissue(gt_rgb):
                        pbar.update(1)
                        continue

                    patch_idx += 1
                    tissue_px += int(np.count_nonzero(self._tissue_mask(gt_rgb)))

                    pred_patch = pred_slide.read_at_magnification((px, py), (tw, th)).convert("RGB")
                    pred_rgb = np.array(pred_patch)
                    pred_patch.close()

                    # ── Independent OTSU per image ────────────────────────────
                    gt_result = self._count_patch(gt_rgb, threshold=None)
                    pred_result = self._count_patch(pred_rgb, threshold=None)

                    g_count, _, _, g_thr, _ = gt_result
                    p_count, _, _, p_thr, _ = pred_result

                    gt_total += g_count
                    pred_total += p_count

                    patch_results.append(
                        {
                            "patch_name": f"patch_{patch_idx:04d}",
                            "gt_count": g_count,
                            "pred_count": p_count,
                            "gt_threshold": round(g_thr, 1),
                            "pred_threshold": round(p_thr, 1),
                            "gt_path": str(gt_path),
                            "pred_path": str(pred_path),
                        }
                    )

                    # ── Save comparison plot ───────────────────────────────────
                    if save_plots and plots_saved < max_plots:
                        fname = str(plots_dir / f"patch_{patch_idx:04d}_x{px}_y{py}.png")
                        _save_comparison_plot(
                            gt_rgb,
                            gt_result,
                            pred_rgb,
                            pred_result,
                            patch_idx,
                            px,
                            py,
                            fname,
                            dpi=dpi,
                        )
                        plots_saved += 1
                        tqdm.write(
                            f"  [PLOT] {plots_saved}/{max_plots}  "
                            f"GT={g_count} (θ={g_thr:.1f})  "
                            f"Pred={p_count} (θ={p_thr:.1f})"
                        )

                    pbar.update(1)

        gt_slide.close()
        pred_slide.close()

        # ── Metrics ───────────────────────────────────────────────────────────
        px_mm2 = (mpp_x / 1000.0) * (mpp_y / 1000.0)
        tissue_area_mm2 = tissue_px * px_mm2
        density_gt = gt_total / tissue_area_mm2 if tissue_area_mm2 > 0 else 0.0
        density_pred = pred_total / tissue_area_mm2 if tissue_area_mm2 > 0 else 0.0
        diff_abs = pred_total - gt_total
        diff_pct = (diff_abs / gt_total * 100) if gt_total > 0 else float("nan")

        print("\n[RESULT] ══════════════════════════════════════════════")
        print(f"[RESULT]  Tissue patches    : {patch_idx}")
        print(f"[RESULT]  GT  DAB+ cells   : {gt_total:,}")
        print(f"[RESULT]  Pred DAB+ cells  : {pred_total:,}")
        print(f"[RESULT]  Δ absolute        : {diff_abs:+,}")
        if gt_total > 0:
            print(f"[RESULT]  Δ relative        : {diff_pct:+.1f}%")
        print(f"[RESULT]  Tissue area       : {tissue_area_mm2:.3f} mm²")
        print(f"[RESULT]  GT  density       : {density_gt:.1f} cells/mm²")
        print(f"[RESULT]  Pred density      : {density_pred:.1f} cells/mm²")
        if save_plots:
            print(f"[RESULT]  Plots saved       : {plots_saved}  →  {plots_dir}")
        print("[RESULT] ══════════════════════════════════════════════")

        summary = {
            "gt_slide": Path(gt_path).name,
            "pred_slide": Path(pred_path).name,
            "label": label,
            "gt_positive": int(gt_total),
            "pred_positive": int(pred_total),
            "diff_absolute": int(diff_abs),
            "diff_pct": round(diff_pct, 2) if gt_total > 0 else None,
            "tissue_area_mm2": round(tissue_area_mm2, 4),
            "tissue_pixels": int(tissue_px),
            "tissue_area_method": "ground_truth_pixel_mask",
            "gt_density_per_mm2": round(density_gt, 2),
            "pred_density_per_mm2": round(density_pred, 2),
            "plots_saved": plots_saved,
            "thresholding": "independent_otsu_per_image",
        }

        # JSON
        json_path = out_dir / (f"{Path(gt_path).stem}_vs_{Path(pred_path).stem}_results.json")
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"[INFO]  JSON  → {json_path}")

        # Excel
        excel_path = out_dir / (f"{Path(gt_path).stem}_vs_{Path(pred_path).stem}_counts.xlsx")
        _write_excel(patch_results, str(excel_path))

        return summary

    def count_batch(self, input_dir: str, label: str = "Cell") -> list:
        """Count every supported WSI in a directory.

        Parameters
        ----------
        input_dir : str
            Directory searched non-recursively for supported WSI suffixes.
        label : str, optional
            Human-readable marker label passed to :meth:`count_slide`.

        Returns
        -------
        list of dict
            Successful per-slide result mappings. Failed slides are logged
            and omitted.
        """
        slides = sorted(
            p
            for p in Path(input_dir).iterdir()
            if any(str(p).lower().endswith(ext) for ext in WSI_EXTENSIONS)
        )
        if not slides:
            print(f"[ERROR] No WSI files found in: {input_dir}")
            return []

        print(f"[INFO] Found {len(slides)} slide(s)")
        all_results = []
        for slide_path in slides:
            print(f"\n{'─' * 50}")
            try:
                result = self.count_slide(str(slide_path), label=label)
                all_results.append(result)
            except Exception as e:
                print(f"[ERROR] {slide_path.name}: {e}")

        if all_results:
            tot = sum(r["total_positive"] for r in all_results)
            print("\n[BATCH] ══════════════════════════════════")
            print(f"[BATCH]  Slides  : {len(all_results)}")
            print(f"[BATCH]  Total   : {tot:,} DAB+ cells")
            print("[BATCH] ══════════════════════════════════")

            out = self.layout.module_dir("cell_counting")
            with open(out / "batch_cell_count_results.json", "w") as f:
                json.dump(all_results, f, indent=2)

        return all_results
