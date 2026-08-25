"""Contour-driven ORB registration stages and orchestration."""

from __future__ import annotations

import cv2
import numpy as np

from rocqipath.core.logging import logger
from rocqipath.registration.orb_stages import (
    _estimate_affine,
    _match_contours_spatial,
    _ncc_score,
    _phase_correlation_translation,
    _refine_with_phase_correlation,
    _tissue_mask_od,
    _top_contours,
    _write_qc_overlay,
)


def _register_orb(self) -> None:
    """
    Run the five-stage registration and populate self.orb_matrix.

    Attributes written
    ------------------
    self.orb_matrix    np.ndarray (3, 3) float64   affine in thumbnail-px space
    self.orb_scale     float                        full-res px / thumbnail px
    self.registration_ok bool                       False if NCC gate fails

    Config keys (all optional — self.config dict)
    ---------------------------------------------
    orb_thumb_size        int   1500   coarse thumbnail long-axis (px)
    orb_refine_thumb_size int   3000   refinement thumbnail long-axis (px)
    orb_refine_enabled    bool  True   set False to skip Stage 4
    orb_max_contours      int   8      max contours extracted per slide
    orb_min_area_frac     float 0.001  min contour area / image area
    orb_match_threshold   float 1.4    max score to accept a contour pair
    ransac_threshold      float 20.0   RANSAC reprojection threshold (thumb px)
    min_ncc_threshold     float 0.25   NCC below this → registration_ok = False
    """
    # ================================================================================
    # Helper functions
    # ================================================================================

    # ================================================================================
    # Perform ORB alignment correction
    # ================================================================================
    logger.info("[ORB] Running contour-based cross-stain registration")

    cfg = self.config

    # ── Thumbnails ──────────────────────────────────────────────────────────
    THUMB_MAX = cfg.get("orb_thumb_size", 1500)
    W, H = self.slide_ref.dimensions  # full-res width, height
    if W >= H:
        tw, th = THUMB_MAX, max(1, int(H * THUMB_MAX / W))
    else:
        tw, th = max(1, int(W * THUMB_MAX / H)), THUMB_MAX
    img_ref_rgb = np.array(self.slide_ref.get_thumbnail((tw, th)).convert("RGB"))
    img_tgt_rgb = np.array(self.slide_tgt.get_thumbnail((tw, th)).convert("RGB"))

    # ── Stage 0 — Stain-agnostic tissue masking ─────────────────────────────
    logger.info("[ORB] Stage 0 — OD-channel tissue segmentation…")

    # Ensure target RGB thumbnail matches reference dimensions exactly
    ref_h, ref_w = img_ref_rgb.shape[:2]
    tgt_h, tgt_w = img_tgt_rgb.shape[:2]
    if (tgt_h != ref_h) or (tgt_w != ref_w):
        img_tgt_rgb = cv2.resize(img_tgt_rgb, (ref_w, ref_h), interpolation=cv2.INTER_LINEAR)
        logger.info(f"[ORB] Reshaped target RGB thumbnail from {tgt_w}x{tgt_h} to {ref_w}x{ref_h}")
    target_full_w, target_full_h = self.slide_tgt.dimensions
    self.orb_ref_scale_x = W / ref_w
    self.orb_ref_scale_y = H / ref_h
    self.orb_tgt_scale_x = target_full_w / ref_w
    self.orb_tgt_scale_y = target_full_h / ref_h
    self.orb_scale = self.orb_ref_scale_x  # compatibility attribute
    logger.info(
        "[ORB] Thumbnail {}x{} | ref scale=({:.3f},{:.3f}) target scale=({:.3f},{:.3f})",
        ref_w,
        ref_h,
        self.orb_ref_scale_x,
        self.orb_ref_scale_y,
        self.orb_tgt_scale_x,
        self.orb_tgt_scale_y,
    )

    mask_ref = _tissue_mask_od(img_ref_rgb)
    mask_tgt = _tissue_mask_od(img_tgt_rgb)

    img_ref_gray = cv2.cvtColor(img_ref_rgb, cv2.COLOR_RGB2GRAY)
    img_tgt_gray = cv2.cvtColor(img_tgt_rgb, cv2.COLOR_RGB2GRAY)

    # Ensure target thumbnail matches reference dimensions exactly
    ref_h, ref_w = img_ref_gray.shape[:2]
    tgt_h, tgt_w = img_tgt_gray.shape[:2]
    if (tgt_h != ref_h) or (tgt_w != ref_w):
        img_tgt_gray = cv2.resize(img_tgt_gray, (ref_w, ref_h), interpolation=cv2.INTER_LINEAR)
        logger.info(f"[ORB] Reshaped target thumbnail from {tgt_w}x{tgt_h} to {ref_w}x{ref_h}")

    # ── Stage 1 — Phase-correlation coarse translation prior ────────────────
    logger.info("[ORB] Stage 1 — Phase-correlation coarse translation…")
    pc_dx, pc_dy = _phase_correlation_translation(img_ref_gray, img_tgt_gray)
    logger.info(f"[ORB]   Phase-corr translation prior: Δx={pc_dx:.1f}px  Δy={pc_dy:.1f}px")

    # ── Stage 2 — Contour extraction & matching ─────────────────────────────
    logger.info("[ORB] Stage 2 — Contour matching (shape + spatial descriptor)…")
    N_CONTOURS = cfg.get("orb_max_contours", 8)
    MIN_AREA = cfg.get("orb_min_area_frac", 0.001)

    cnts_ref = _top_contours(mask_ref, N_CONTOURS, MIN_AREA)
    cnts_tgt = _top_contours(mask_tgt, N_CONTOURS, MIN_AREA)
    logger.info(f"[ORB]   Tissue contours — ref: {len(cnts_ref)}, tgt: {len(cnts_tgt)}")

    if not cnts_ref or not cnts_tgt:
        logger.warning(
            "[ORB] WARNING: No tissue contours found. Falling back to phase-correlation only."
        )
        matched_src, matched_dst = [], []
    else:
        MATCH_THRESH = cfg.get("orb_match_threshold", 1.4)
        matched_src, matched_dst = _match_contours_spatial(
            cnts_ref,
            cnts_tgt,
            mask_ref.shape,
            mask_tgt.shape,
            match_threshold=MATCH_THRESH,
        )

    logger.info(f"[ORB]   Matched contour pairs: {len(matched_src)}")

    # ── Stage 3 — Affine estimation ─────────────────────────────────────────
    logger.info("[ORB] Stage 3 — Affine estimation…")
    RANSAC_THR = cfg.get("ransac_threshold", 20.0)
    M = _estimate_affine(
        matched_src,
        matched_dst,
        pc_dx,
        pc_dy,
        mask_ref,
        mask_tgt,
        ransac_threshold=RANSAC_THR,
    )

    if M is None:
        raise RuntimeError("[ORB] Affine estimation failed (RANSAC returned None).")

    # Promote 2×3 → 3×3 homogeneous
    M3 = np.vstack([M, [0.0, 0.0, 1.0]]).astype(np.float64)

    # ── Stage 4 — Phase-correlation residual refinement ─────────────────────
    REFINE_SIZE = cfg.get("orb_refine_thumb_size", 3000)
    if cfg.get("orb_refine_enabled", True):
        logger.info(f"[ORB] Stage 4 — Residual refinement at {REFINE_SIZE}px…")
        try:
            M3 = _refine_with_phase_correlation(
                self,
                M3,
                ref_w,
                REFINE_SIZE,
            )
            logger.info("[ORB]   Refinement applied.")
        except Exception as exc:
            logger.warning(f"[ORB] WARNING: Refinement failed ({exc}). Using coarse matrix.")
    else:
        logger.info("[ORB] Stage 4 — Refinement disabled (orb_refine_enabled=False).")

    self.orb_matrix = M3

    # ── Stage 5 — NCC quality gate ───────────────────────────────────────────
    logger.info("[ORB] Stage 5 — NCC quality validation…")
    h_t, w_t = img_tgt_gray.shape[:2]
    warped = cv2.warpAffine(img_ref_gray, M3[:2].astype(np.float64), (w_t, h_t))
    ncc = _ncc_score(warped, img_tgt_gray, mask_tgt)
    logger.info(f"[ORB]   NCC score (tissue-masked): {ncc:.4f}")

    MIN_NCC = cfg.get("min_ncc_threshold", 0.25)
    if ncc < MIN_NCC:
        logger.warning(f"[ORB] WARNING: NCC {ncc:.4f} < threshold {MIN_NCC}. Registration flagged.")
        self.registration_ok = False
    else:
        self.registration_ok = True

    # ── QC overlay ───────────────────────────────────────────────────────────
    _write_qc_overlay(
        warped,
        img_tgt_gray,
        matched_src,
        matched_dst,
        self.output_dir,
        ncc_score=ncc,
    )

    logger.info(f"[ORB] Registration complete. ok={self.registration_ok}  NCC={ncc:.4f}")
