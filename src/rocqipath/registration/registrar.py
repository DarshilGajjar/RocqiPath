# -*- coding: utf-8 -*-
"""Register paired WSIs and expose aligned patch operations.

Provides two public classes:

``ValisConfig``
    Typed dataclass of VALIS hyper-parameters.  Pass to ``WSIRegistrar``
    to tune registration quality without touching internal defaults.

``WSIRegistrar``
    Registers a paired H&E / IHC whole-slide image (WSI) and extracts
    spatially aligned patch pairs.

    Workflow::

        reg = WSIRegistrar(he_path, ihc_path, cfg)
        reg.register_slides(method="valis")   # or "orb"
        thumb, valid_grids = reg.generate_grid_map()
        reg.extract_patch_pair(grid_id=5)
        reg.save_aligned_wsi(level=0)
        reg.close()

Registration methods
--------------------
``"valis"``
    Full rigid + non-rigid registration via the VALIS library
    (``pip install valis-wsi``).

``"orb"``
    Lightweight contour-shape affine registration — stain-agnostic fallback
    that works without VALIS.

Author  : Darshil Gajjar
"""

__all__ = ["ValisConfig", "WSIRegistrar"]

import os
import shutil
import tempfile
from typing import Optional, Tuple


try:
    import openslide  # type: ignore

    HAS_OPENSLIDE = True
except (ImportError, OSError):
    openslide = None  # type: ignore[assignment]
    HAS_OPENSLIDE = False

# ── VALIS (optional) ───────────────────────────────────────────────────────────
# VALIS is imported lazily so the rest of the pipeline can still run
# (e.g. ORB fallback or reference-only mode) without a VALIS installation.
from rocqipath.config import ValisConfig
from rocqipath.core.logging import logger
from rocqipath.core.magnification import (
    DEFAULT_TARGET_MAGNIFICATION,
    MagnificationPlan,
    build_magnification_plan,
    objective_magnification_from_properties,
)
from rocqipath.core.output import OutputLayout
from rocqipath.registration.export import RegistrationExportMixin
from rocqipath.registration.orb_backend import OrbBackendMixin
from rocqipath.registration.patches import PatchGridMixin
from rocqipath.registration.quality import RegistrationQualityMixin
from rocqipath.registration.valis_backend import (
    HAS_VALIS,
    ValisBackendMixin,
    build_matcher,  # noqa: F401 - compatibility for prior internal imports
)
from rocqipath.utils.geometry import transform_coords


#: Objective powers a scanner is plausibly reporting. Used to snap a magnification
#: derived from measured um/px onto its nominal value.
STANDARD_OBJECTIVES = (1.0, 2.0, 2.5, 4.0, 5.0, 10.0, 20.0, 40.0, 60.0, 100.0)

#: Relative distance within which a derived magnification is snapped.
OBJECTIVE_SNAP_TOLERANCE = 0.05


def magnification_fallback(properties, explicit=None):
    """Resolve a base objective magnification when the slide does not state one.

    Generic pyramidal TIFFs carry no ``openslide.objective-power``, but they do
    carry a resolution tag, from which OpenSlide derives ``openslide.mpp-x``.
    Deriving magnification from physical pixel size is strictly better than
    falling back to a hard-coded constant, because it is at least measured.

    The 10 um/px == 1x mapping is the usual histology convention (20x is
    nominally 0.5 um/px), not a physical law -- if you need exactness, work in
    um/px directly rather than round-tripping through magnification.

    Parameters
    ----------
    properties : mapping
        ``OpenSlide.properties``.
    explicit : float or None
        Caller-supplied override.  Wins over everything.

    Returns
    -------
    float or None
        ``None`` means "no better information than the library default".
    """
    if explicit:
        return float(explicit)
    for key in ("openslide.mpp-x", "openslide.mpp-y"):
        raw = properties.get(key)
        try:
            mpp = float(raw)
        except (TypeError, ValueError):
            continue
        if mpp <= 0:
            continue

        derived = 10.0 / mpp

        # Snap to the nearest standard objective. A measured value never lands
        # exactly on the nominal one -- 0.5031 um/px derives 19.8768x, and
        # build_magnification_plan then rejects a nominal 20x target as
        # "exceeding" the slide. Snapping also avoids resampling every patch by
        # a fraction of a percent for no gain. Beyond the tolerance the raw
        # value is kept, since a genuinely odd scan should not be rounded into
        # a lie -- pass reference_source_magnification/
        # moving_source_magnification explicitly in that case.
        nearest = min(STANDARD_OBJECTIVES, key=lambda s: abs(s - derived) / s)
        if abs(nearest - derived) / nearest <= OBJECTIVE_SNAP_TOLERANCE:
            logger.info(
                f"[ZOOM] No objective-power; derived {derived:.3f}x from "
                f"{key}={mpp:.4f} um/px -> snapped to {nearest:g}x"
            )
            return nearest

        logger.warning(
            f"[ZOOM] No objective-power; derived {derived:.3f}x from "
            f"{key}={mpp:.4f} um/px, which is not within "
            f"{OBJECTIVE_SNAP_TOLERANCE:.0%} of a standard objective. Using it "
            f"as-is; set the source magnification explicitly if this is wrong."
        )
        return derived
    return None


# ══════════════════════════════════════════════════════════════════════════════
# WSIRegistrar — main pipeline class
# ══════════════════════════════════════════════════════════════════════════════


class WSIRegistrar(
    ValisBackendMixin,
    RegistrationQualityMixin,
    RegistrationExportMixin,
    OrbBackendMixin,
    PatchGridMixin,
):
    """Register paired WSIs and extract spatially aligned patches.

    Workflow
    ────────
    1. Instantiate with slide paths and a config dict.
    2. Call ``register_slides()`` to run VALIS (or ORB fallback).
    3. Call ``generate_grid_map()`` to identify tissue-containing grid cells.
    4. Call ``extract_patch_pair()`` (or ``extract_single_patch()``) per grid cell.
    5. Call ``close()`` to release file handles and clean up temp files.

    Parameters
    ----------
    ──────────
    path_ref : str
        Absolute path to the H&E (reference / fixed) slide.
    path_tgt : str or None
        Absolute path to the IHC (moving) slide.
        Pass None for reference-only (single-slide) mode.
    config : dict
        Pipeline configuration. Expected keys:
          - patch_size              : int   — patch edge length in pixels
          - grid_density            : int   — number of grid rows/cols
          - base_output_dir         : str   — root directory for all outputs
          - target_magnification    : float — physical zoom for both slides (default 20x)
          - overlay_max_px          : int   — (optional) max edge for QC overlay images
          - orb_thumb_size          : int   — (optional) thumbnail size for ORB fallback
          - ransac_threshold        : float — (optional) RANSAC reprojection threshold
    valis_cfg : ValisConfig, optional
        Fine-grained VALIS parameters. Defaults to ``ValisConfig()``.
    """

    # ──────────────────────────────────────────────────────────────────────────
    # Construction
    # ──────────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        path_ref: str,
        path_tgt: Optional[str],
        config: dict,
        valis_cfg: Optional[ValisConfig] = None,
    ) -> None:
        """Open the reference (and optional target) slide and initialise state.

        Parameters
        ----------
        path_ref : str
            Path to the H&E (reference / fixed) slide. Resolved to an
            absolute path immediately via :func:`os.path.abspath`, and
            opened synchronously with OpenSlide before this constructor
            returns.
        path_tgt : str or None
            Path to the IHC (moving) slide, or ``None`` to construct the
            registrar in reference-only (single-slide) mode — in which
            case ``self.slide_tgt`` stays ``None`` and no target-slide
            operations (registration, aligned-WSI export) are available.
        config : dict
            Pipeline configuration dict — see the class docstring above
            for the full list of expected keys (``patch_size``,
            ``grid_density``, ``base_output_dir``, etc.). Stored verbatim
            on ``self.config``; not validated at construction time.
        valis_cfg : ValisConfig, optional
            Fine-grained VALIS hyperparameters. When omitted, a default
            ``ValisConfig()`` is constructed.

        Attributes
        ----------
        Beyond the parameters stored directly (``self.config``,
        ``self.valis_cfg``, ``self.path_ref``, ``self.path_tgt``), this
        constructor also initialises:

        - ``self.method`` (str or None) — set to ``"valis"`` or ``"orb"``
          once :meth:`register_slides` has run; ``None`` beforehand.
        - ``self.registration_ok`` (bool) — whether registration has
          succeeded; ``False`` until then.
        - ``self.valis_obj``, ``self._registrar``, ``self._slide_ref_valis``,
          ``self._slide_tgt_valis``, ``self.registration_error_df`` —
          VALIS-specific state, populated later by the internal
          ``_register_valis`` method; all ``None`` at construction.
        - ``self.orb_matrix``, ``self.orb_scale`` — ORB-fallback state,
          populated later by the internal ``_register_orb`` method; both
          ``None`` at construction.
        - ``self.slide_ref`` / ``self.slide_tgt`` — open
          :class:`openslide.OpenSlide` handles for the reference and
          (if provided) target slides.
        - ``self.w``, ``self.h`` — base-level (level 0) pixel dimensions
          of the reference slide.
        - ``self.ref_name``, ``self.tgt_name``, ``self.base_name`` —
          convenience filename strings derived from the slide paths.

        Notes
        -----
        Opening the slides via OpenSlide happens synchronously inside
        this constructor, so instantiating a ``WSIRegistrar`` is not free
        — it performs real file I/O and will raise whatever OpenSlide
        raises if a path is invalid or the format is unsupported (e.g.
        :class:`openslide.OpenSlideError`). Callers should call
        :meth:`close` when finished to release these file handles.
        """
        self._initialize_state(path_ref, path_tgt, config, valis_cfg)
        self._open_slides()
        self._initialize_magnification()
        self._initialize_output()
        self._check_physical_field_ratio(config.get("max_physical_field_ratio"))
        self._check_patch_grid_viability()

    def _initialize_state(
        self,
        path_ref: str,
        path_tgt: Optional[str],
        config: dict,
        valis_cfg: Optional[ValisConfig],
    ) -> None:
        """Initialize paths and empty backend state without opening slides."""
        self.config = config
        self.valis_cfg = valis_cfg or ValisConfig()
        self.path_ref = os.path.abspath(path_ref)
        self.path_tgt = os.path.abspath(path_tgt) if path_tgt else None
        self.method: Optional[str] = None
        self.registration_ok = False
        self.valis_obj: Optional[object] = None
        self._registrar: Optional[object] = None
        self._slide_ref_valis = None
        self._slide_tgt_valis = None
        self.registration_error_df = None
        self.orb_matrix = None
        self.orb_scale: Optional[float] = None
        self.orb_ref_scale_x: Optional[float] = None
        self.orb_ref_scale_y: Optional[float] = None
        self.orb_tgt_scale_x: Optional[float] = None
        self.orb_tgt_scale_y: Optional[float] = None

    def _open_slides(self) -> None:
        """Open reference and optional target slides with the existing logs."""
        if not HAS_OPENSLIDE:
            raise ImportError(
                "OpenSlide is required for registration. Install 'rocqipath[orb]' "
                "or 'rocqipath[valis]'."
            )
        logger.info(f"[LOADING] Ref : {os.path.basename(self.path_ref)}")
        self.slide_ref = openslide.OpenSlide(self.path_ref)
        self.w, self.h = self.slide_ref.dimensions  # base-level (level 0) dimensions

        if self.path_tgt:
            logger.info(f"[LOADING] Tgt : {os.path.basename(self.path_tgt)}")
            self.slide_tgt = openslide.OpenSlide(self.path_tgt)
        else:
            logger.info("[LOADING] No target slide — reference-only mode.")
            self.slide_tgt = None

    def _initialize_magnification(self) -> None:
        """Resolve independent physical magnification plans for both slides."""
        config = self.config
        target_magnification = float(
            config.get("target_magnification", DEFAULT_TARGET_MAGNIFICATION)
        )
        ref_base, ref_source = objective_magnification_from_properties(
            self.slide_ref.properties,
            fallback=magnification_fallback(
                self.slide_ref.properties,
                config.get("reference_source_magnification"),
            ),
        )
        self.ref_magnification_plan = build_magnification_plan(
            ref_base, target_magnification, self.slide_ref.level_downsamples
        )
        self.target_w, self.target_h = self.ref_magnification_plan.target_dimensions(
            self.slide_ref.dimensions
        )
        self.tgt_magnification_plan: Optional[MagnificationPlan] = None
        if self.slide_tgt is not None:
            # NOTE: alignment.py writes "moving_source_magnification"; the
            # older "target_source_magnification" is accepted for callers that
            # predate the tgt -> moving rename.  Reading only the old key meant
            # the moving slide's override was silently discarded.
            tgt_base, tgt_source = objective_magnification_from_properties(
                self.slide_tgt.properties,
                fallback=magnification_fallback(
                    self.slide_tgt.properties,
                    config.get(
                        "moving_source_magnification",
                        config.get("target_source_magnification"),
                    ),
                ),
            )
            self.tgt_magnification_plan = build_magnification_plan(
                tgt_base, target_magnification, self.slide_tgt.level_downsamples
            )
            logger.info(
                f"[ZOOM] Ref={ref_base:g}x ({ref_source}), "
                f"Tgt={tgt_base:g}x ({tgt_source}) -> {target_magnification:g}x"
            )
        else:
            logger.info(f"[ZOOM] Ref={ref_base:g}x ({ref_source}) -> {target_magnification:g}x")

    def _initialize_output(self) -> None:
        """Create the case output and VALIS working directories."""
        config = self.config
        self.ref_name = os.path.basename(self.path_ref)
        self.tgt_name = os.path.basename(self.path_tgt) if self.path_tgt else None
        self.base_name = os.path.splitext(self.ref_name)[0]
        item_name = config.get("output_item_name", self.base_name)
        self.output_dir = str(
            OutputLayout(config["base_output_dir"]).item_dir("alignment", item_name)
        )
        self.keep_valis_diagnostics = bool(config.get("keep_valis_diagnostics", True))
        if self.keep_valis_diagnostics:
            self.temp_dir = os.path.join(self.output_dir, "valis")
            os.makedirs(self.temp_dir, exist_ok=True)
        else:
            self.temp_dir = tempfile.mkdtemp(prefix="valis_proc_")

    # ══════════════════════════════════════════════════════════════════════════
    # Construction-time sanity checks
    # ══════════════════════════════════════════════════════════════════════════

    def _check_physical_field_ratio(self, max_ratio) -> None:
        """Compare the reference and moving physical canvases at target zoom.

        Previously this config key was written by ``alignment.py`` and never
        read here, so the documented guard did not exist.

        Note the limitation: when neither slide states an objective power and
        neither has usable ``mpp``, both fall back to the same constant and
        this degenerates into a pixel-count comparison.  That case is logged
        explicitly rather than presented as a physical check.
        """
        if self.tgt_magnification_plan is None:
            return

        tgt_w, tgt_h = self.tgt_magnification_plan.target_dimensions(self.slide_tgt.dimensions)
        ratios = [
            max(self.target_w, tgt_w) / max(1, min(self.target_w, tgt_w)),
            max(self.target_h, tgt_h) / max(1, min(self.target_h, tgt_h)),
        ]
        worst = max(ratios)
        logger.info(
            f"[ZOOM] Physical target canvases: reference={self.target_w}x{self.target_h}, "
            f"moving={tgt_w}x{tgt_h}, max ratio={worst:.3f}"
        )
        if max_ratio is not None and worst > float(max_ratio):
            raise ValueError(
                f"Reference/moving physical field ratio {worst:.3f} exceeds "
                f"max_physical_field_ratio={max_ratio}. The two slides do not "
                f"cover comparable areas at the target magnification."
            )

    # ══════════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════════

    def register_slides(self, method: str = "valis") -> None:
        """
        Run slide registration.

        Parameters
        ----------
        ──────────
        method : str
            "valis" — full rigid + non-rigid registration via the VALIS library.
            "orb"   — lightweight contour-shape-based affine registration
                      (stain-agnostic fallback; no VALIS required).

        Raises
        ------
        ──────
        ImportError  : if method="valis" and VALIS is not installed.
        RuntimeError : if registration fails or QC threshold is exceeded.
        """
        self.method = method.lower()
        if self.method == "valis":
            if not HAS_VALIS:
                raise ImportError("VALIS is not installed. Install with:  pip install valis-wsi")
            self._register_valis()
        elif self.method == "orb":
            self._register_orb()
        else:
            raise NotImplementedError(f"Unsupported registration method: {method}")

    def close(self) -> None:
        """
        Release all resources held by this registrar.

        Actions
        ───────
        - Closes OpenSlide file handles for ref and tgt slides.
        - Deletes the VALIS temporary directory (intermediate files).
        - Kills the JVM that VALIS/BioFormats may have started.

        Always call this method when the registrar is no longer needed,
        ideally inside a ``try/finally`` block or via a context manager.
        """
        self.slide_ref.close()
        if self.slide_tgt:
            self.slide_tgt.close()

        # Remove VALIS scratch files only when diagnostics were not requested.
        if not getattr(self, "keep_valis_diagnostics", False) and os.path.isdir(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

        # VALIS starts a JVM for BioFormats; kill it cleanly.
        # if HAS_VALIS:
        #     try:
        #         registration.kill_jvm()
        #     except Exception:
        #         pass

    # ══════════════════════════════════════════════════════════════════════════
    # VALIS registration
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════════
    # ORB / contour-shape registration
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════════
    # coordinate transform
    # ══════════════════════════════════════════════════════════════════════════

    def _transform_coords(self, x: int, y: int) -> Tuple[Optional[int], Optional[int]]:
        """Map a base-level reference coordinate into the target slide."""
        return transform_coords(self, x, y)
