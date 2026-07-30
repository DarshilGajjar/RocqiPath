"""Pure, separately testable stages used by contour-based registration."""

from __future__ import annotations

import os

import cv2
import numpy as np

from rocqipath.core.logging import logger
from rocqipath.core.tissue import optical_density_otsu_mask


def _tissue_mask_od(rgb: np.ndarray) -> np.ndarray:
    """
    Binary tissue mask via Otsu thresholding on the OD max-channel.

    Returns
    -------
    mask : np.ndarray, shape (H, W), dtype uint8
        255 = tissue, 0 = background.
    """
    return optical_density_otsu_mask(
        rgb,
        scale=85.0,
        kernel_size=(15, 15),
        close_iterations=3,
        open_iterations=2,
    )


def _phase_correlation_translation(
    gray_ref: np.ndarray,
    gray_tgt: np.ndarray,
) -> tuple[float, float]:
    """Estimate translation with normalized FFT phase correlation.

    A Hanning window suppresses spectral leakage at image borders, making
    the estimate robust to tissue extent differences across slides.
    Normalisation of the cross-power spectrum makes the peak sharp even
    when stain-induced intensity distributions differ substantially.

    Parameters
    ----------
    gray_ref, gray_tgt : np.ndarray, shape (H, W), dtype uint8 or float

    Returns
    -------
    dx, dy : float
        Estimated translation in pixels such that
        tgt ≈ ref shifted by (dx, dy).
        Positive dx  → ref is to the left of tgt.
    """
    h, w = gray_ref.shape[:2]
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)

    f_ref = np.fft.fft2(gray_ref.astype(np.float32) * win)
    f_tgt = np.fft.fft2(gray_tgt.astype(np.float32) * win)

    cross = f_ref * np.conj(f_tgt)
    denom = np.abs(cross) + 1e-8
    cross /= denom  # normalised cross-power spectrum

    cc = np.fft.ifft2(cross).real
    idx = np.unravel_index(np.argmax(cc), cc.shape)

    dy = float(idx[0]) if idx[0] < h // 2 else float(idx[0]) - h
    dx = float(idx[1]) if idx[1] < w // 2 else float(idx[1]) - w
    return dx, dy


def _top_contours(
    mask: np.ndarray,
    n: int = 8,
    min_area_frac: float = 0.001,
) -> list:
    """Return the largest external contours above an area threshold.

    Slide labels and small artefacts are filtered out.
    """
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = mask.shape[0] * mask.shape[1] * min_area_frac
    cnts = [c for c in cnts if cv2.contourArea(c) > min_area]
    return sorted(cnts, key=cv2.contourArea, reverse=True)[:n]


def _contour_features(
    cnt: np.ndarray,
    img_shape: tuple[int, int],
) -> np.ndarray:
    """Compute a four-dimensional contour feature vector.

    Combine shape statistics with normalized spatial position.

    Features
    --------
    [0] solidity    — area / convex-hull area  ∈ (0, 1]
                    Distinguishes compact lobules from branching vessels.
    [1] aspect      — bounding-box width / height  (log-scaled for symmetry)
    [2] cx_norm     — centroid x / image width     ∈ [0, 1]
    [3] cy_norm     — centroid y / image height    ∈ [0, 1]

    Normalised position allows matching contours across slides with different
    magnification, while penalising spatially inconsistent pairings.
    """
    area = cv2.contourArea(cnt)
    hull_area = cv2.contourArea(cv2.convexHull(cnt))
    solidity = area / (hull_area + 1e-6)

    x, y, bw, bh = cv2.boundingRect(cnt)
    aspect = float(bw) / (bh + 1e-6)

    M = cv2.moments(cnt)
    if M["m00"] > 0:
        cx = (M["m10"] / M["m00"]) / img_shape[1]
        cy = (M["m01"] / M["m00"]) / img_shape[0]
    else:
        cx, cy = 0.5, 0.5

    return np.array([solidity, np.log1p(aspect), cx, cy], dtype=np.float32)


def _match_contours_spatial(
    cnts_ref: list,
    cnts_tgt: list,
    shape_ref: tuple[int, int],
    shape_tgt: tuple[int, int],
    match_threshold: float = 1.4,
) -> tuple[list, list]:
    """
    Greedy nearest-neighbour matching of contours across slides.

    Each ref contour is matched to the best-scoring tgt contour (not yet used)
    by combining:
        • Hu-moment shape similarity  (cv2.matchShapes, weight 0.5)
        • L2 distance in feature space [solidity, log-aspect, cx, cy]
        with per-dimension weights [2.0, 1.5, 0.8, 0.8]

    Position features are weighted lower than shape features so that
    moderate slide offsets do not prevent correct matching.

    Parameters
    ----------
    match_threshold : float
        Combined score threshold.  Lower = stricter.  Default 1.4 is
        permissive enough for cross-stain use while rejecting random pairings.

    Returns
    -------
    matched_src, matched_dst : list of [x, y] centroid coordinates
        In thumbnail pixel space of the respective slide.
    """
    WEIGHTS = np.array([2.0, 1.5, 0.8, 0.8], dtype=np.float32)

    feats_ref = [_contour_features(c, shape_ref) for c in cnts_ref]
    feats_tgt = [_contour_features(c, shape_tgt) for c in cnts_tgt]

    matched_src, matched_dst = [], []
    used_tgt = set()

    for i, cr in enumerate(cnts_ref):
        best_score, best_j, best_ct = float("inf"), -1, None

        for j, ct in enumerate(cnts_tgt):
            if j in used_tgt:
                continue
            hu_score = cv2.matchShapes(cr, ct, cv2.CONTOURS_MATCH_I2, 0)
            feat_dist = float(np.linalg.norm((feats_ref[i] - feats_tgt[j]) * WEIGHTS))
            combined = feat_dist + 0.5 * hu_score

            if combined < best_score:
                best_score, best_j, best_ct = combined, j, ct

        if best_score < match_threshold and best_j >= 0:
            Mr = cv2.moments(cr)
            Mt = cv2.moments(best_ct)
            if Mr["m00"] > 0 and Mt["m00"] > 0:
                matched_src.append([Mr["m10"] / Mr["m00"], Mr["m01"] / Mr["m00"]])
                matched_dst.append([Mt["m10"] / Mt["m00"], Mt["m01"] / Mt["m00"]])
                used_tgt.add(best_j)

    return matched_src, matched_dst


def _estimate_affine(
    matched_src: list,
    matched_dst: list,
    pc_dx: float,
    pc_dy: float,
    mask_ref: np.ndarray,
    mask_tgt: np.ndarray,
    ransac_threshold: float = 20.0,
) -> np.ndarray | None:
    """Estimate an affine matrix from matched contour centroids.

    Use the following degradation ladder:

        ≥ 3 pairs  → full affine via RANSAC (rotation + scale + translation + shear)
        2 pairs  → translation + rotation (mean of two pair estimates)
        1 pair   → pure translation
        0 pairs  → phase-correlation translation (preferred over centroid fallback)

    The phase-correlation prior (pc_dx, pc_dy) is used in the 0-pair case
    instead of the original centroid-to-centroid delta, which was sensitive
    to asymmetric tissue coverage between slides.

    Returns
    -------
    M : np.ndarray, shape (2, 3), float32
        Affine matrix, or None if RANSAC fails with ≥ 3 pairs (caller raises).
    """
    n = len(matched_src)

    if n >= 3:
        logger.info(f"[ORB]   {n} pairs → full affine (RANSAC).")
        src_pts = np.float32(matched_src).reshape(-1, 1, 2)
        dst_pts = np.float32(matched_dst).reshape(-1, 1, 2)
        M, _ = cv2.estimateAffinePartial2D(
            src_pts,
            dst_pts,
            method=cv2.RANSAC,
            ransacReprojThreshold=ransac_threshold,
            maxIters=5000,
            confidence=0.99,
        )
        return M  # may be None if RANSAC fails — caller handles

    elif n == 2:
        logger.info("[ORB]   2 pairs → translation + rotation estimate.")
        dx = float(np.mean([d[0] - s[0] for s, d in zip(matched_src, matched_dst)]))
        dy = float(np.mean([d[1] - s[1] for s, d in zip(matched_src, matched_dst)]))
        return np.float32([[1, 0, dx], [0, 1, dy]])

    elif n == 1:
        logger.info("[ORB]   1 pair → pure translation.")
        dx = matched_dst[0][0] - matched_src[0][0]
        dy = matched_dst[0][1] - matched_src[0][1]
        return np.float32([[1, 0, dx], [0, 1, dy]])

    else:
        # 0 matches — use phase-correlation prior (far better than centroid delta)
        logger.info("[ORB]   0 matches — using phase-correlation translation as fallback.")
        return np.float32([[1, 0, pc_dx], [0, 1, pc_dy]])


def _refine_with_phase_correlation(
    self,
    M3_coarse: np.ndarray,
    orig_tw: int,
    refine_size: int = 3000,
) -> np.ndarray:
    """Refine an affine matrix on higher-resolution thumbnails.

    Estimate the residual translation using phase correlation.

    Algorithm
    ---------
    1. Request a larger thumbnail (refine_size px on the long axis).
    2. Scale the coarse affine's translation to the new pixel space.
    3. Warp the reference thumbnail using the scaled affine.
    4. Estimate the residual (dx, dy) between warped-ref and target via
    phase correlation.
    5. Compose a pure-translation correction on top of the scaled affine.
    6. Scale translation back to original thumbnail coordinates.

    The higher resolution reduces quantisation error and allows the
    phase-correlation peak to be located more precisely, typically
    improving alignment by 2–8 pixels at full scan resolution.

    Parameters
    ----------
    self         : registration object (needs .slide_ref, .slide_tgt, .w, .h)
    M3_coarse    : np.ndarray, shape (3, 3)   — coarse affine in orig-thumb space
    orig_tw      : int   — width of the original thumbnail
    refine_size  : int   — long-axis size for the refinement thumbnail

    Returns
    -------
    M3_refined : np.ndarray, shape (3, 3), float64
        Updated affine matrix still expressed in *original* thumbnail space.
    """
    W, H = self.slide_ref.dimensions
    if W >= H:
        rtw = refine_size
        rth = max(1, int(H * refine_size / W))
    else:
        rtw = max(1, int(W * refine_size / H))
        rth = refine_size

    ref_hi = np.array(self.slide_ref.get_thumbnail((rtw, rth)).convert("L"), dtype=np.float32)
    tgt_hi = np.array(self.slide_tgt.get_thumbnail((rtw, rth)).convert("L"), dtype=np.float32)
    if tgt_hi.shape != ref_hi.shape:
        tgt_hi = cv2.resize(
            tgt_hi, (ref_hi.shape[1], ref_hi.shape[0]), interpolation=cv2.INTER_LINEAR
        )

    # Scale factor from original thumbnail to refinement thumbnail
    up = rtw / orig_tw

    # Upscale coarse affine translation to refinement resolution
    M_hi = M3_coarse.copy()
    M_hi[0, 2] *= up
    M_hi[1, 2] *= up

    warped_ref = cv2.warpAffine(ref_hi, M_hi[:2], (rtw, rth))
    res_dx, res_dy = _phase_correlation_translation(warped_ref, tgt_hi)
    logger.info(
        f"[ORB]   Residual correction: Δx={res_dx:.2f}px  Δy={res_dy:.2f}px "
        f"(at {refine_size}px resolution)"
    )

    # Compose residual correction
    M_residual = np.eye(3, dtype=np.float64)
    M_residual[0, 2] = res_dx
    M_residual[1, 2] = res_dy

    M_refined = M_residual @ M_hi

    # Scale translation back to original thumbnail space
    M_refined[0, 2] /= up
    M_refined[1, 2] /= up

    return M_refined


def _ncc_score(
    img_a: np.ndarray,
    img_b: np.ndarray,
    mask: np.ndarray | None = None,
) -> float:
    """
    Normalised cross-correlation (NCC) between two single-channel images.

    NCC ∈ [-1, 1]:
        ~1.0  →  excellent alignment
        ~0.5  →  moderate alignment
        ~0.25 →  poor (threshold for flagging)
        ≤ 0   →  likely failed registration

    Parameters
    ----------
    img_a, img_b : np.ndarray, shape (H, W)
    mask         : optional uint8 mask — if provided, only masked pixels
                (value > 0) are included in the computation, focusing the
                score on tissue regions rather than background.

    Returns
    -------
    ncc : float
    """
    if mask is not None:
        idx = mask > 0
        a = img_a[idx].astype(np.float32)
        b = img_b[idx].astype(np.float32)
    else:
        a = img_a.astype(np.float32).ravel()
        b = img_b.astype(np.float32).ravel()

    a -= a.mean()
    b -= b.mean()
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-8
    return float(np.dot(a, b) / denom)


def _write_qc_overlay(
    warped_ref_gray: np.ndarray,
    tgt_gray: np.ndarray,
    matched_src: list,
    matched_dst: list,
    output_dir: str,
    ncc_score: float = float("nan"),
) -> None:
    """Save a false-colour registration QC overlay.

        Green channel = warped H&E reference
        Red   channel = IHC target

    Perfect alignment → grey.  Misalignment → coloured fringing.

    Matched contour centroids are annotated:
        Cyan circles    = reference centroids (in warped space)
        Magenta circles = target centroids
        White lines     = correspondence pairs

    NCC score is rendered in the top-left corner.
    """
    h_t, w_t = tgt_gray.shape[:2]
    overlay = np.zeros((h_t, w_t, 3), dtype=np.uint8)
    overlay[..., 1] = warped_ref_gray  # green = warped ref (H&E)
    overlay[..., 2] = tgt_gray  # red   = target (IHC)

    # Annotate matched pairs
    for (sx, sy), (dx, dy) in zip(matched_src, matched_dst):
        cv2.circle(overlay, (int(sx), int(sy)), 8, (0, 255, 255), 2)  # cyan
        cv2.circle(overlay, (int(dx), int(dy)), 8, (255, 0, 255), 2)  # magenta
        cv2.line(overlay, (int(sx), int(sy)), (int(dx), int(dy)), (255, 255, 255), 1)

    # NCC annotation
    label = f"NCC={ncc_score:.4f}"
    cv2.putText(
        overlay,
        label,
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    out_path = os.path.join(output_dir, "orb_registration_overlay.png")
    cv2.imwrite(out_path, overlay)
    logger.info(f"[ORB] QC overlay saved → {out_path}")


__all__ = [
    "_tissue_mask_od",
    "_phase_correlation_translation",
    "_top_contours",
    "_contour_features",
    "_match_contours_spatial",
    "_estimate_affine",
    "_refine_with_phase_correlation",
    "_ncc_score",
    "_write_qc_overlay",
]
