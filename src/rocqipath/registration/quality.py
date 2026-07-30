"""Registration quality gates and VALIS QC image generation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Tuple

import cv2
import numpy as np

from rocqipath.core.logging import logger
from rocqipath.utils.geometry import resize_twostep as _resize_twostep

try:
    from PIL import Image as _PILImage  # noqa: F401

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class RegistrationQualityMixin:
    """Methods mixed into :class:`WSIRegistrar`."""

    def _check_registration_quality(self, error_df) -> None:
        """Check VALIS registration error against the configured threshold.

        Error metric
        ────────────
        VALIS reports the median feature-point distance after non-rigid
        registration in the ``*_D`` columns of ``error_df``. When slide
        resolution (µm/px) is available, the error is converted to µm using:

            error_µm = error_px_processed × (full_res_px / processed_res_px) × µm_per_px

        The conversion accounts for the fact that VALIS computes distances at
        ``max_processed_image_dim_px`` resolution, not at full resolution.

        Side effects
        ────────────
        Always saves ``valis_registration_summary.csv`` to ``self.output_dir``
        for offline inspection, regardless of whether the threshold is exceeded.

        Raises
        ------
        ──────
        RuntimeError : if ``valis_cfg.max_acceptable_error_um`` is set and the
                       computed error exceeds it.
        """
        csv_path = os.path.join(self.output_dir, "valis_registration_summary.csv")

        if error_df is None or error_df.empty:
            logger.info("[QC] No error_df returned by VALIS — skipping QC check.")
            return

        # Find the primary error column (prefer non-rigid distance columns)
        err_cols = [c for c in error_df.columns if "non_rigid" in c and c.endswith("D")]
        if not err_cols:
            err_cols = [c for c in error_df.columns if c.endswith("D")]

        if not err_cols:
            logger.info(f"[QC] No error columns found. Available: {list(error_df.columns)}")
            error_df.to_csv(csv_path, index=False)
            return

        mean_err = error_df[err_cols[0]].mean()
        unit = "px"

        # Convert to µm when resolution metadata is available
        if "resolution" in error_df.columns:
            res = error_df["resolution"].dropna()
            if not res.empty:
                # Scale from processed-resolution pixels → full-resolution µm.
                # VALIS fits the LONGEST edge to max_processed_image_dim_px, so
                # using self.w under-reports the error on portrait slides (by
                # 28% on a 8112x11349 section) and over-reports on landscape.
                processed_dim = (
                    getattr(self, "_effective_processed_dim", 0)
                    or self.valis_cfg.max_processed_image_dim_px
                )
                scale = max(self.w, self.h) / processed_dim
                res_um_per_px = res.mean()
                mean_err_um = mean_err * scale * res_um_per_px
                logger.info(
                    f"[QC] Mean registration error: "
                    f"{mean_err:.2f} px (processed @ {processed_dim} px)  "
                    f"≈  {mean_err_um:.2f} µm"
                )
                unit = "µm"
                mean_err = mean_err_um
            else:
                logger.info(f"[QC] Mean registration error: {mean_err:.2f} {unit}")

        # Write the summary BEFORE the gate — the failing cases are exactly the
        # ones worth inspecting, and raising first meant their CSV never landed.
        error_df.to_csv(csv_path, index=False)
        logger.info(f"[QC] Registration summary saved → {csv_path}")

        # Enforce threshold if configured
        threshold = self.valis_cfg.max_acceptable_error_um
        if threshold is not None and unit == "µm" and mean_err > threshold:
            raise RuntimeError(
                f"[QC] Registration error {mean_err:.2f} µm exceeds "
                f"threshold {threshold} µm. Aborting patch extraction."
            )

    def _save_valis_overlay(self) -> None:
        """
        Generate and save three registration QC images at high resolution.

        Image sources
        ─────────────
        Uses ``Slide.warp_slide()`` to read from a WSI pyramid level that fits
        within ``config['overlay_max_px']`` (default 4 000 px). This bypasses
        the ``max_image_dim_px`` cap that applies to ``warp_img()``.
        Falls back to ``warp_img()`` if ``warp_slide()`` raises an exception.

        Output files
        ────────────
        valis_registration_overlay.png
            50/50 alpha blend of H&E and IHC. Preserves stain colours.
            Good for checking gross alignment.

        valis_registration_sidebyside.png
            H&E and IHC placed side-by-side with a 6 px white separator.
            Good for visual comparison of tissue morphology.

        valis_registration_diffmap.png
            Per-pixel absolute difference rendered with the HOT colormap
            (black → red → yellow → white = low → high difference).
            Bright regions indicate misalignment or stain-specific signal.
            Background is masked to white.
        """
        try:
            TARGET_MAX_PX = self.config.get("overlay_max_px", 4000)

            def _warp_hires(slide_valis) -> np.ndarray:
                """Return a warped RGB image at a bounded pyramid level.

                Falls back to ``warp_img()`` if ``warp_slide()`` is unavailable
                or raises an exception.
                """
                try:
                    dims = slide_valis.slide_dimensions_wh  # list of (w, h) per level
                    # Iterate from level 0 (highest res) downward; stop at first fit
                    chosen_level = len(dims) - 1  # safe default = lowest res
                    for lvl, (lw, lh) in enumerate(dims):
                        if max(lw, lh) <= TARGET_MAX_PX:
                            chosen_level = lvl
                            break
                    logger.info(
                        f"[VALIS] Overlay: level {chosen_level} "
                        f"({dims[chosen_level][0]}×{dims[chosen_level][1]} px) "
                        f"— {slide_valis.name}"
                    )
                    img = slide_valis.warp_slide(chosen_level)
                    return np.array(img) if not isinstance(img, np.ndarray) else img
                except Exception as exc:
                    logger.warning(
                        f"[WARN] warp_slide() failed ({exc}), falling back to warp_img()"
                    )
                    return slide_valis.warp_img()

            # ── Warp both slides ───────────────────────────────────────────
            img_ref = _warp_hires(self._slide_ref_valis)
            img_tgt = _warp_hires(self._slide_tgt_valis)

            # Resize IHC to match H&E canvas (should already match, but be safe)
            h, w = img_ref.shape[:2]
            img_tgt_r = cv2.resize(img_tgt, (w, h), interpolation=cv2.INTER_LINEAR)

            # ── Shared background mask ─────────────────────────────────────
            # Pixels that are background in *both* slides are set to white in
            # all output images to avoid misleading colour artefacts.
            def _bg_mask(rgb: np.ndarray) -> np.ndarray:
                """Return a binary background mask.

                A value of 255 denotes glass and 0 denotes tissue.
                Uses Otsu thresholding on the L channel of LAB colour space,
                which is robust across different stain types.
                """
                lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
                L = lab[..., 0]
                _, mask = cv2.threshold(L, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                return mask  # 255 = background

            bg_both = cv2.bitwise_and(_bg_mask(img_ref), _bg_mask(img_tgt_r))

            # ── 1. Alpha blend (50/50) ─────────────────────────────────────
            blend = cv2.addWeighted(
                img_ref.astype(np.float32),
                0.5,
                img_tgt_r.astype(np.float32),
                0.5,
                0,
            ).astype(np.uint8)
            blend[bg_both == 255] = 255

            out_blend = os.path.join(self.output_dir, "valis_registration_overlay.png")
            cv2.imwrite(out_blend, cv2.cvtColor(blend, cv2.COLOR_RGB2BGR))
            logger.info(f"[VALIS] Blend overlay saved    → {out_blend}  ({w}×{h} px)")

            # ── 2. Side-by-side ────────────────────────────────────────────
            sep = np.full((h, 6, 3), 255, dtype=np.uint8)  # 6 px white separator
            sbs = np.concatenate([img_ref, sep, img_tgt_r], axis=1)

            out_sbs = os.path.join(self.output_dir, "valis_registration_sidebyside.png")
            cv2.imwrite(out_sbs, cv2.cvtColor(sbs, cv2.COLOR_RGB2BGR))
            logger.info(f"[VALIS] Side-by-side saved     → {out_sbs}  ({sbs.shape[1]}×{h} px)")

            # ── 3. Difference map (HOT colormap) ───────────────────────────
            # absdiff → grayscale → HOT colormap (already BGR from applyColorMap)
            diff = cv2.absdiff(img_ref, img_tgt_r)
            diff_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
            diff_color = cv2.applyColorMap(diff_gray, cv2.COLORMAP_HOT)  # BGR output
            diff_color[bg_both == 255] = 255  # white background

            out_diff = os.path.join(self.output_dir, "valis_registration_diffmap.png")
            cv2.imwrite(out_diff, diff_color)
            logger.info(f"[VALIS] Diff map saved         → {out_diff}  ({w}×{h} px)")

        except Exception as exc:
            logger.warning(f"[WARN] Could not save QC overlays: {exc}")


def _read_hq_center_crop(
    slide: Any,
    physical_l0_px: int,
    read_level: int,
    out_px: int,
) -> Tuple[Any, int, float]:
    """
    Read a square centre crop from *slide* at *read_level*.

    The physical window is defined in level-0 pixels so both reference and moving slides
    represent the same tissue area.  The result is resampled to
    *out_px × out_px* via the two-step BOX→LANCZOS method.

    Returns
    -------
    (PIL.Image, level_used, downsample_used)
    """
    read_level = max(0, min(int(read_level), slide.level_count - 1))
    ds = float(slide.level_downsamples[read_level])
    w0, h0 = slide.level_dimensions[0]
    cx0, cy0 = w0 // 2, h0 // 2
    half = physical_l0_px // 2

    x0 = max(0, cx0 - half)
    y0 = max(0, cy0 - half)

    wl, hl = slide.level_dimensions[read_level]
    req = max(1, int(round(physical_l0_px / ds)))
    req_w = min(req, max(1, wl - int(x0 / ds)))
    req_h = min(req, max(1, hl - int(y0 / ds)))

    img = slide.read_region((x0, y0), read_level, (req_w, req_h)).convert("RGB")
    return _resize_twostep(img, out_px), read_level, ds


def qc_center_patch_side_by_side(
    reference_path: str,
    moving_path: str,
    out_png: str,
    *,
    reference_level: int = 3,
    patch_size: int = 512,
    reference_read_level: int = 0,
    moving_read_level: int = 0,
    title: str = "",
    dpi: int = 300,
    show: bool = False,
) -> str:
    """
    Save a side-by-side centre-patch QC PNG for a registered pair.

    The physical window is defined by *patch_size* pixels at *reference_level*
    on the reference pyramid so both panels show the same tissue area regardless
    of the pyramid structure of the aligned moving file.

    Parameters
    ----------
    reference_path, moving_path : str
        Paths to the reference and aligned moving WSIs (openslide-compatible).
    out_png : str
        Destination PNG path (parent directories are created automatically).
    reference_level : int
        Reference pyramid level that defines the zoom window.
    patch_size : int
        Output size in pixels for each panel.
    reference_read_level, moving_read_level : int
        Pyramid level to *read* from (0 = maximum quality).
    title : str
        Optional ``suptitle`` on the figure.
    dpi : int
        Figure DPI.
    show : bool
        Call ``plt.show()`` after saving.

    Returns
    -------
    str
        Absolute path to the saved PNG.

    Raises
    ------
    RuntimeError
        When Pillow, openslide, or matplotlib are not installed.
    FileNotFoundError
        When either WSI path does not exist.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for QC output.  pip install Pillow")
    try:
        import openslide
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(f"Missing QC dependency: {exc}") from exc

    for label, p in (("Reference", reference_path), ("Moving", moving_path)):
        if not Path(p).is_file():
            raise FileNotFoundError(f"{label} file not found: {p}")

    reference_slide = openslide.OpenSlide(str(reference_path))
    moving_slide = openslide.OpenSlide(str(moving_path))
    try:
        resolved_reference_level = min(reference_level, reference_slide.level_count - 1)
        ds_ref = float(reference_slide.level_downsamples[resolved_reference_level])
        physical_l0_px = int(round(patch_size * ds_ref))

        reference_img, reference_read_level_used, reference_ds = _read_hq_center_crop(
            reference_slide, physical_l0_px, reference_read_level, patch_size
        )
        moving_img, moving_read_level_used, moving_ds = _read_hq_center_crop(
            moving_slide, physical_l0_px, moving_read_level, patch_size
        )

        fig, axes = plt.subplots(1, 2, figsize=(12, 6))
        axes[0].imshow(reference_img, interpolation="none")
        axes[0].set_title(
            f"Reference L{resolved_reference_level} (ds={ds_ref:.2f}) | "
            f"read-L{reference_read_level_used} (ds={reference_ds:.2f})\n"
            f"{patch_size} px output from {physical_l0_px} L0 px window"
        )
        axes[0].axis("off")

        axes[1].imshow(moving_img, interpolation="none")
        axes[1].set_title(
            f"Moving read-L{moving_read_level_used} (ds={moving_ds:.2f})\n"
            f"same physical window — {patch_size} px output"
        )
        axes[1].axis("off")

        if title:
            fig.suptitle(title, fontsize=14, fontweight="bold")

        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_png, dpi=dpi, bbox_inches="tight")
        if show:
            plt.show()
        plt.close(fig)

        logger.info(f"[QC] Saved: {out_png}")
        return str(Path(out_png).resolve())
    finally:
        reference_slide.close()
        moving_slide.close()
