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
from functools import lru_cache

from rocqipath.core.logging import logger

__all__ = [
    # "HAS_VALIS",
    # "HAS_VALIS_FEATURES",
    # "ValisBackendMixin",
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
def build_matcher(
    detector_name: str = "disk",
    num_features: int = 2000,
    rgb: bool = False,
):
    """Build a VALIS feature detector + matcher pair.

    Pairing rules, verified against the VALIS source:

    * ``DiskFD`` and ``DeDoDeFD`` subclass ``KorniaFD`` and expose
      ``light_glue_feature_name``, so they pair with ``LightGlueMatcher``.
      They accept ``num_features``.
    * ``SuperPointFD`` does **not** subclass ``KorniaFD`` and has no
      ``light_glue_feature_name``; passing it to ``LightGlueMatcher`` raises
      ``AttributeError`` inside ``set_fd``.  It must use ``SuperGlueMatcher``,
      and its base ``FeatureDD.__init__`` does not accept ``num_features``.

    Parameters
    ----------
    detector_name : str
        ``"disk"`` (default), ``"dedode"``, or ``"superpoint"``.
    num_features : int
        Keypoint budget.  Ignored for SuperPoint.
    rgb : bool
        Detect on RGB rather than the processed single-channel image.

    Returns
    -------
    Matcher instance, or ``None`` when unavailable -- in which case the caller
    should simply omit the ``matcher`` argument and let VALIS choose.
    """
    if not detector_name:
        return None

    feature_detectors, feature_matcher = _load_valis_features()
    if feature_detectors is None or feature_matcher is None:
        return None

    builders = {
        "disk": ("DiskFD", True),
        "dedode": ("DeDoDeFD", True),
        "superpoint": ("SuperPointFD", False),
    }
    key = detector_name.lower()
    if key not in builders:
        logger.warning(
            f"[VALIS] Unknown feature_detector {detector_name!r}; "
            f"expected one of {sorted(builders)}. Using VALIS defaults."
        )
        return None

    cls_name, is_kornia = builders[key]
    detector_cls = getattr(feature_detectors, cls_name, None)
    if detector_cls is None:
        logger.warning(
            f"[VALIS] {cls_name} not present in this valis version. Using VALIS defaults."
        )
        return None

    try:
        kwargs = {"rgb": bool(rgb)}
        if is_kornia:
            kwargs["num_features"] = int(num_features)
        detector = detector_cls(**kwargs)

        if is_kornia:
            return feature_matcher.LightGlueMatcher(detector)

        matcher_cls = getattr(feature_matcher, "SuperGlueMatcher", None)
        if matcher_cls is None:
            logger.warning("[VALIS] SuperGlueMatcher unavailable. Using defaults.")
            return None
        return matcher_cls(feature_detector=detector)

    except Exception as exc:
        logger.warning(f"[VALIS] Could not build {cls_name} matcher ({exc}). Using defaults.")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Registrar mixin
# ─────────────────────────────────────────────────────────────────────────────
class ValisBackendMixin:
    """Methods mixed into :class:`WSIRegistrar`."""

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
                "importable. Install it with: pip install -e \".[valis]\" "
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

        # DISK + LightGlue (VALIS 1.2.0+ default). Set explicitly so the same
        # detector is used regardless of the installed VALIS version.
        matcher = build_matcher(cfg.feature_detector, cfg.num_features, cfg.rgb_features)
        if matcher is not None:
            valis_init_kwargs["matcher"] = matcher
            logger.info(
                f"        matcher                    = "
                f"{matcher.__class__.__name__}({cfg.feature_detector}, "
                f"n={cfg.num_features})"
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
            optional = ("matcher", "norm_method", "check_for_reflections")
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
            logger.info(f"[VALIS] Custom image processors for {len(cfg.processor_dict)} key(s)")
        rigid_reg, non_rigid_reg, error_df = self.valis_obj.register(
            processor_dict=cfg.processor_dict
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
                logger.info(
                    f"[VALIS] Running micro registration at {cfg.register_micro_dim_px} px..."
                )
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