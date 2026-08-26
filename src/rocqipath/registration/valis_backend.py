"""VALIS registration backend and feature-matcher construction.

Import policy
─────────────
Nothing in this module imports ``valis`` at module scope.  Importing VALIS
costs ~7 s and instantiates LightGlue/SuperPoint matchers as a side effect
(printing "Loaded LightGlue model" twice), which every unrelated pipeline --
patch extraction, ORB alignment, stain normalisation -- would otherwise pay.

VALIS is loaded on first actual use via :func:`_load_valis` /
:func:`_load_valis_features`, both memoised so the cost is paid once per
process.  ``HAS_VALIS`` and ``HAS_VALIS_FEATURES`` remain importable and are
resolved through the module-level ``__getattr__`` using ``find_spec``, which
locates a module without executing it.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Optional
from functools import lru_cache

from rocqipath.core.logging import logger

__all__ = [
    "_register_valis",
    "build_matcher",
    "valis_default_warper",
]


# ─────────────────────────────────────────────────────────────────────────────
# Lazy VALIS loading
# ─────────────────────────────────────────────────────────────────────────────
def _module_available(name: str) -> bool:
    """Report whether ``name`` is importable *without* executing it.

    Weaker than a try/except import: a VALIS whose import fails at runtime
    (missing native libvips/OpenSlide, for instance) still reports ``True``
    here.  Real failures surface at the call site, where they are handled.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@lru_cache(maxsize=1)
def _load_valis():
    """Import VALIS on first use.

    Returns
    -------
    tuple
        ``(registration_module, OpticalFlowWarper_cls)``, or ``(None, None)``
        when VALIS is not installed or fails to import.
    """
    try:
        from valis import registration
        from valis.non_rigid_registrars import OpticalFlowWarper

        return registration, OpticalFlowWarper
    except (ImportError, OSError) as exc:
        logger.debug(f"[VALIS] unavailable: {exc}")
        return None, None


@lru_cache(maxsize=1)
def _load_valis_features():
    """Import the VALIS feature-detector/matcher modules on first use.

    Returns ``(feature_detectors, feature_matcher)`` or ``(None, None)``.
    """
    try:
        from valis import feature_detectors, feature_matcher

        return feature_detectors, feature_matcher
    except (ImportError, OSError) as exc:
        logger.debug(f"[VALIS] feature modules unavailable: {exc}")
        return None, None


def valis_default_warper():
    """Return VALIS's ``OpticalFlowWarper``, or ``None`` if VALIS is absent.

    Use this instead of a module-level constant so that config defaults do not
    drag VALIS into every import of the config module.
    """
    return _load_valis()[1]


def __getattr__(name):
    """Resolve the legacy module-level names without importing VALIS eagerly.

    Keeps ``from rocqipath.registration.valis_backend import HAS_VALIS`` (and
    ``registration``) working for existing callers.
    """
    if name == "HAS_VALIS":
        return _module_available("valis")
    if name == "HAS_VALIS_FEATURES":
        return _module_available("valis.feature_detectors")
    if name == "registration":
        return _load_valis()[0]
    if name == "_VALIS_DEFAULT_WARPER":
        return _load_valis()[1]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__) | {"registration"})

# ─────────────────────────────────────────────────────────────────────────────
# Feature detector / matcher construction
# ─────────────────────────────────────────────────────────────────────────────
_FEATURE_DETECTOR_ALIASES = {
    "disk": "DiskFD",
    "dedode": "DeDoDeFD",
    "superpoint": "SuperPointFD",
    "orb": "OrbFD",
    "brisk": "BriskFD",
    "kaze": "KazeFD",
    "akaze": "AkazeFD",
    "daisy": "DaisyFD",
    "latch": "LatchFD",
    "boost": "BoostFD",
    "vgg": "VggFD",
    "orb_vgg": "OrbVggFD",
    "censure_vgg": "CensureVggFD",
}


_MATCHER_ALIASES = {
    "lightglue": "LightGlueMatcher",
    "superglue": "SuperGlueMatcher",
    "descriptor": "Matcher",
    "generic": "Matcher",
}


def build_feature_detector(
    detector_name: str,
    *,
    num_features: int = 2000,
    rgb: bool = False,
    detector_kwargs: Optional[dict] = None,
):
    """Instantiate a VALIS feature detector by alias or class name."""

    if not detector_name:
        return None

    feature_detectors, _ = _load_valis_features()

    if feature_detectors is None:
        return None

    kwargs = dict(detector_kwargs or {})

    key = detector_name.lower()

    class_name = _FEATURE_DETECTOR_ALIASES.get(
        key,
        detector_name,
    )

    detector_cls = getattr(
        feature_detectors,
        class_name,
        None,
    )

    if detector_cls is None:
        raise ValueError(
            f"Unknown VALIS feature detector {detector_name!r}. "
            f"No class named {class_name!r} exists in "
            f"valis.feature_detectors."
        )

    # Kornia-based detectors such as DISK and DeDoDe support these.
    kornia_base = getattr(feature_detectors, "KorniaFD", None)

    if (
        kornia_base is not None
        and isinstance(detector_cls, type)
        and issubclass(detector_cls, kornia_base)
    ):
        kwargs.setdefault(
            "num_features",
            int(num_features),
        )

        kwargs.setdefault(
            "rgb",
            bool(rgb),
        )

    return detector_cls(**kwargs)


def build_matcher(
    detector_name: str = "disk",
    matcher_name: str = "auto",
    *,
    num_features: int = 2000,
    rgb: bool = False,
    detector_kwargs: Optional[dict] = None,
    matcher_kwargs: Optional[dict] = None,
):
    """Build a VALIS detector + matcher combination."""

    if not detector_name:
        return None

    feature_detectors, feature_matcher = _load_valis_features()

    if feature_detectors is None or feature_matcher is None:
        return None

    detector = build_feature_detector(
        detector_name,
        num_features=num_features,
        rgb=rgb,
        detector_kwargs=detector_kwargs,
    )

    matcher_kwargs = dict(matcher_kwargs or {})

    requested_matcher = (
        matcher_name.lower()
        if isinstance(matcher_name, str)
        else matcher_name
    )

    # --------------------------------------------------------------
    # Let installed VALIS choose its native default.
    # --------------------------------------------------------------
    if requested_matcher in {
        None,
        "valis_default",
        "default",
    }:
        return None

    # --------------------------------------------------------------
    # Automatically determine the appropriate matcher.
    # --------------------------------------------------------------
    if requested_matcher == "auto":
        kornia_base = getattr(
            feature_detectors,
            "KorniaFD",
            None,
        )

        superpoint_cls = getattr(
            feature_detectors,
            "SuperPointFD",
            None,
        )

        if (
            kornia_base is not None
            and isinstance(detector, kornia_base)
        ):
            requested_matcher = "lightglue"

        elif (
            superpoint_cls is not None
            and isinstance(detector, superpoint_cls)
        ):
            requested_matcher = "superglue"

        else:
            requested_matcher = "descriptor"

    # --------------------------------------------------------------
    # Resolve alias or exact VALIS class name.
    # --------------------------------------------------------------
    class_name = _MATCHER_ALIASES.get(
        requested_matcher,
        matcher_name,
    )

    matcher_cls = getattr(
        feature_matcher,
        class_name,
        None,
    )

    if matcher_cls is None:
        raise ValueError(
            f"Unknown VALIS matcher {matcher_name!r}. "
            f"No class named {class_name!r} exists in "
            f"valis.feature_matcher."
        )

    # --------------------------------------------------------------
    # Validate known incompatible combinations.
    # --------------------------------------------------------------
    if class_name == "LightGlueMatcher":
        kornia_base = getattr(
            feature_detectors,
            "KorniaFD",
            None,
        )

        if (
            kornia_base is None
            or not isinstance(detector, kornia_base)
        ):
            raise ValueError(
                "VALIS LightGlueMatcher requires a "
                "KorniaFD-compatible feature detector. "
                "Use DiskFD/DeDoDeFD, or matcher='auto'."
            )

    return matcher_cls(
        feature_detector=detector,
        **matcher_kwargs,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Registrar mixin
# ─────────────────────────────────────────────────────────────────────────────
def _register_valis(self) -> None:
    """
    Run the full VALIS rigid + non-rigid registration pipeline.

    Pipeline steps
    ──────────────
    1. Initialise ``registration.Valis`` with parameters from ``self.valis_cfg``.
    2. Call ``valis_obj.register()`` → rigid alignment, then non-rigid warp.
    3. Optionally run ``valis_obj.register_micro()`` for a higher-res
       non-rigid refinement pass (controlled by ``valis_cfg.run_register_micro``).
    4. Cache per-slide ``Slide`` objects for coordinate mapping.
    5. Save QC overlay images via ``_save_valis_overlay()``.
    6. Validate registration error via ``_check_registration_quality()``.

    Design notes
    ────────────
    - VALIS is imported here, not at module scope, so unrelated pipelines
      do not pay the ~7 s import and LightGlue model load.
    - ``max_processed_image_dim_px`` (not ``max_image_dim_px``) controls
      feature detection resolution. The VALIS paper recommends 850-1 000 px
      for WSI registration.
    - ``align_to_reference=True`` pins H&E as the fixed anchor so only the
      IHC slide is warped. ``False`` (default) computes a consensus space.
    - ``Slide.warp_xy_from_to()`` is used for coordinate mapping -- this is
      the correct per-slide API (not the deprecated ``Valis.warp_xy``).
    """
    registration, default_warper = _load_valis()
    if registration is None:
        raise RuntimeError(
            "VALIS is required for alignment_method='valis' but is not "
            'importable. Install it with: pip install -e ".[valis]" '
            "(and ensure the native libvips/OpenSlide runtimes are on PATH)."
        )

    cfg = self.valis_cfg

    # Config defaults may legitimately be None so that importing the config
    # module does not import VALIS; resolve them now that VALIS is loaded.
    non_rigid_cls = cfg.non_rigid_registrar_cls or default_warper

    logger.info("[VALIS] Initialising registration pipeline...")
    logger.info(f"        max_processed_image_dim_px = {cfg.max_processed_image_dim_px}")
    logger.info(f"        max_non_rigid_reg_dim_px   = {cfg.max_non_rigid_reg_dim_px}")
    logger.info(f"        align_to_reference         = {cfg.align_to_reference}")
    logger.info(f"        non_rigid_registrar_cls    = {non_rigid_cls}")

    valis_init_kwargs = dict(
        src_dir=os.path.dirname(self.path_ref),  # fallback scan directory
        dst_dir=self.temp_dir,
        img_list=[self.path_ref, self.path_tgt],  # explicit slide pair
        reference_img_f=self.ref_name,  # H&E = fixed reference
        align_to_reference=cfg.align_to_reference,
        max_image_dim_px=cfg.max_image_dim_px,
        max_processed_image_dim_px=cfg.max_processed_image_dim_px,
        max_non_rigid_registration_dim_px=cfg.max_non_rigid_reg_dim_px,
        thumbnail_size=cfg.thumbnail_size,
        non_rigid_registrar_cls=non_rigid_cls,
        micro_rigid_registrar_cls=cfg.micro_rigid_registrar_cls,
        micro_rigid_registrar_params=cfg.micro_rigid_registrar_params,
        imgs_ordered=cfg.imgs_ordered,
        crop=cfg.crop,
        check_for_reflections=cfg.check_for_reflections,
    )
    if cfg.norm_method is not None:
        valis_init_kwargs["norm_method"] = cfg.norm_method

    # ------------------------------------------------------------------
    # Main rigid matcher
    # ------------------------------------------------------------------
    matcher = build_matcher(
        detector_name=cfg.feature_detector,
        matcher_name=cfg.matcher,
        num_features=cfg.num_features,
        rgb=cfg.rgb_features,
        detector_kwargs=cfg.feature_detector_kwargs,
        matcher_kwargs=cfg.matcher_kwargs,
    )

    if matcher is not None:
        valis_init_kwargs["matcher"] = matcher

        logger.info(
            f"        matcher                    = "
            f"{matcher.__class__.__name__}"
        )

        logger.info(
            f"        feature detector           = "
            f"{matcher.feature_detector.__class__.__name__}"
        )


    # ------------------------------------------------------------------
    # Optional sorting/orientation matcher
    # ------------------------------------------------------------------
    if (
        cfg.sorting_feature_detector is not None
        or cfg.sorting_matcher is not None
    ):
        sorting_detector = (
            cfg.sorting_feature_detector
            or "vgg"
        )

        sorting_matcher = build_matcher(
            detector_name=sorting_detector,
            matcher_name=cfg.sorting_matcher or "auto",
            num_features=cfg.num_features,
            rgb=False,
            detector_kwargs=(
                cfg.sorting_feature_detector_kwargs
            ),
            matcher_kwargs=(
                cfg.sorting_matcher_kwargs
            ),
        )

        if sorting_matcher is not None:
            valis_init_kwargs[
                "matcher_for_sorting"
            ] = sorting_matcher

            logger.info(
                f"        sorting matcher            = "
                f"{sorting_matcher.__class__.__name__}"
            )

            logger.info(
                f"        sorting feature detector   = "
                f"{sorting_matcher.feature_detector.__class__.__name__}"
            )

    # Escape hatch: anything not covered by a typed field. Applied last, so
    # a caller-supplied value wins over the baseline above -- building one
    # dict and update()-ing it is also what avoids "got multiple values for
    # keyword argument".
    if cfg.valis_kwargs:
        clashes = sorted(set(cfg.valis_kwargs) & set(valis_init_kwargs))
        if clashes:
            logger.info(f"[VALIS] valis_kwargs overrides: {clashes}")
        valis_init_kwargs.update(cfg.valis_kwargs)

    # Record what was actually used; the um error conversion depends on it.
    self._effective_processed_dim = int(
        valis_init_kwargs.get("max_processed_image_dim_px", cfg.max_processed_image_dim_px)
    )
    long_edge = max(self.w, self.h)
    try:
        mpp = float(self.slide_ref.properties.get("openslide.mpp-x", 0.0))
    except (TypeError, ValueError):
        mpp = 0.0
    if mpp > 0:
        logger.info(
            f"        feature resolution         = "
            f"{mpp * long_edge / self._effective_processed_dim:.2f} um/px"
        )

    try:
        self.valis_obj = registration.Valis(**valis_init_kwargs)
    except TypeError as exc:
        # Older VALIS releases do not accept every keyword above. Drop the
        # optional ones and retry rather than failing the whole case.
        optional = ("matcher", "matcher_for_sorting", "norm_method", "check_for_reflections")
        dropped = [k for k in optional if k in valis_init_kwargs]
        if not dropped:
            raise
        logger.warning(
            f"[VALIS] registration.Valis rejected {dropped} ({exc}). "
            f"Retrying without them -- upgrade valis-wsi to use DISK+LightGlue."
        )
        for k in dropped:
            valis_init_kwargs.pop(k, None)
        self.valis_obj = registration.Valis(**valis_init_kwargs)

    logger.info("[VALIS] Running registration (rigid + non-rigid)...")

    if cfg.processor_dict:
        logger.info(
            f"[VALIS] Custom image processors for "
            f"{len(cfg.processor_dict)} key(s)"
        )

    rigid_reg, non_rigid_reg, error_df = self.valis_obj.register(
        processor_dict=cfg.processor_dict
    )

    # ------------------------------------------------------------------
    # Validate VALIS registration
    # ------------------------------------------------------------------
    if rigid_reg is None or rigid_reg is False:
        self.registration_ok = False

        raise RuntimeError(
            "VALIS registration failed: register() returned no rigid "
            "registration result. Review the VALIS traceback above for "
            "the underlying error."
        )

    # ── Optional: second non-rigid micro pass ──────────────────────────
    if cfg.run_register_micro:
        if cfg.register_micro_dim_px <= cfg.max_non_rigid_reg_dim_px:
            logger.warning(
                f"[VALIS] register_micro_dim_px ({cfg.register_micro_dim_px}) "
                f"must be > max_non_rigid_reg_dim_px ({cfg.max_non_rigid_reg_dim_px}). "
                f"Skipping micro pass."
            )
        else:
            logger.info(f"[VALIS] Running micro registration at {cfg.register_micro_dim_px} px...")
            non_rigid_reg, error_df = self.valis_obj.register_micro(
                max_non_rigid_registration_dim_px=cfg.register_micro_dim_px,
                processor_dict=cfg.processor_dict,
            )

    self.registration_error_df = error_df

    # ── Cache registrar alias and per-slide Slide objects ─────────────
    # self._registrar is used by save_aligned_wsi() to call
    # warp_and_save_slide() without exposing valis_obj directly.
    self._registrar = self.valis_obj
    self._slide_ref_valis = self.valis_obj.get_slide(self.ref_name)
    self._slide_tgt_valis = self.valis_obj.get_slide(self.tgt_name)

    # ── QC outputs ─────────────────────────────────────────────────────
    self._save_valis_overlay()
    self._check_registration_quality(error_df)

    self.registration_ok = True
    logger.info("[VALIS] Registration complete.")
