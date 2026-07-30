"""VALIS registration backend and feature-matcher construction."""

from __future__ import annotations

import os

from rocqipath.core.logging import logger

try:
    from valis import registration
    from valis.non_rigid_registrars import (
        OpticalFlowWarper as _OpticalFlowWarper,
    )

    _VALIS_DEFAULT_WARPER = _OpticalFlowWarper
    HAS_VALIS = True
except (ImportError, OSError):
    registration = _VALIS_DEFAULT_WARPER = None
    HAS_VALIS = False

try:
    from valis import feature_detectors, feature_matcher

    HAS_VALIS_FEATURES = True
except (ImportError, OSError):
    feature_detectors = feature_matcher = None
    HAS_VALIS_FEATURES = False


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
    Matcher instance, or ``None`` when unavailable — in which case the caller
    should simply omit the ``matcher`` argument and let VALIS choose.
    """
    if not HAS_VALIS_FEATURES or not detector_name:
        return None

    builders = {
        "disk": ("DiskFD", False),
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
        - ``max_processed_image_dim_px`` (not ``max_image_dim_px``) controls
          feature detection resolution. The VALIS paper recommends 850–1 000 px
          for WSI registration.
        - ``align_to_reference=True`` pins H&E as the fixed anchor so only the
          IHC slide is warped. ``False`` (default) computes a consensus space.
        - ``Slide.warp_xy_from_to()`` is used for coordinate mapping — this is
          the correct per-slide API (not the deprecated ``Valis.warp_xy``).
        """
        cfg = self.valis_cfg
        logger.info("[VALIS] Initialising registration pipeline...")
        logger.info(f"        max_processed_image_dim_px = {cfg.max_processed_image_dim_px}")
        logger.info(f"        max_non_rigid_reg_dim_px   = {cfg.max_non_rigid_reg_dim_px}")
        logger.info(f"        align_to_reference         = {cfg.align_to_reference}")
        logger.info(f"        non_rigid_registrar_cls    = {cfg.non_rigid_registrar_cls}")

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
            non_rigid_registrar_cls=cfg.non_rigid_registrar_cls,
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
                f"Retrying without them — upgrade valis-wsi to use DISK+LightGlue."
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
