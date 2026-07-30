"""Unit coverage for decomposed contour-registration stages."""

from __future__ import annotations

import cv2
import numpy as np

from rocqipath.registration.orb_stages import (
    _contour_features,
    _estimate_affine,
    _match_contours_spatial,
    _ncc_score,
    _phase_correlation_translation,
    _top_contours,
)


def test_phase_correlation_recovers_integer_translation() -> None:
    """Recover the inverse shift that maps a translated target to reference."""
    reference = np.zeros((64, 64), dtype=np.uint8)
    reference[20:30, 22:35] = 255
    target = np.roll(
        np.roll(reference, 5, axis=1),
        -3,
        axis=0,
    )

    assert _phase_correlation_translation(reference, target) == (-5.0, 3.0)


def test_contour_detection_features_and_matching() -> None:
    """Sort contours by area and self-match their spatial descriptors."""
    mask = np.zeros((100, 100), dtype=np.uint8)
    cv2.rectangle(mask, (5, 5), (24, 24), 255, -1)
    cv2.rectangle(mask, (50, 50), (89, 89), 255, -1)

    contours = _top_contours(mask, n=5, min_area_frac=0.001)
    source, target = _match_contours_spatial(
        contours,
        contours,
        mask.shape,
        mask.shape,
    )

    assert [cv2.contourArea(contour) for contour in contours] == [
        1521.0,
        361.0,
    ]
    assert _contour_features(contours[0], mask.shape).shape == (4,)
    assert source == target == [[69.5, 69.5], [14.5, 14.5]]


def test_affine_fallback_and_ncc_stage() -> None:
    """Preserve the zero-match translation fallback and perfect NCC score."""
    image = np.zeros((16, 16), dtype=np.uint8)
    image[4:8, 5:10] = 255

    affine = _estimate_affine([], [], 2.0, -3.0, image, image)

    np.testing.assert_array_equal(
        affine,
        np.array([[1, 0, 2], [0, 1, -3]], dtype=np.float32),
    )
    assert _ncc_score(image, image) == 1.0
