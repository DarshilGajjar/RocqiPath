# -*- coding: utf-8 -*-
"""
rocqipath.registration.core
===================
WSI registration and patch extraction engine.

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

import os
import shutil
import tempfile
import dataclasses
import xml.etree.ElementTree as ET
from tqdm.auto import tqdm
from typing import Optional, Tuple


import cv2  # type: ignore
import numpy as np  # type: ignore
from PIL import Image  # type: ignore

try:
    import openslide  # type: ignore

    HAS_OPENSLIDE = True
except (ImportError, OSError):
    openslide = None  # type: ignore[assignment]
    HAS_OPENSLIDE = False

# ── VALIS (optional) ───────────────────────────────────────────────────────────
# VALIS is imported lazily so the rest of the pipeline can still run
# (e.g. ORB fallback or reference-only mode) without a VALIS installation.
from rocqipath.logger import logger
from rocqipath.magnification import (
    DEFAULT_TARGET_MAGNIFICATION,
    MagnificationPlan,
    build_magnification_plan,
    objective_magnification_from_properties,
)
from rocqipath.output import OutputLayout

try:
    import pyvips

    HAS_PYVIPS = True
except (ImportError, OSError):
    pyvips = None  # type: ignore[assignment]
    HAS_PYVIPS = False

try:
    from valis import registration, warp_tools, slide_io
    from valis.non_rigid_registrars import OpticalFlowWarper

    HAS_VALIS = True
except (ImportError, OSError):
    HAS_VALIS = False
    registration = warp_tools = slide_io = None  # type: ignore[assignment]
    OpticalFlowWarper = None


# ══════════════════════════════════════════════════════════════════════════════
# ValisConfig — VALIS hyper-parameter container
# ══════════════════════════════════════════════════════════════════════════════


@dataclasses.dataclass
class ValisConfig:
    """
    Typed container for VALIS registration hyper-parameters.

    Mirrors the key arguments of ``registration.Valis.__init__()`` so callers
    can tune registration quality without touching the internals of WSIRegistrar.

    Parameter guide
    ───────────────
    max_processed_image_dim_px : int
        Resolution (longest edge, px) at which feature detection runs.
        VALIS default = 512 px; recommended for WSI = 850-1 500 px.
        Higher → better matching, slower.

    max_image_dim_px : int
        Hard cap on the image loaded into RAM for registration.
        VALIS default = 1 024 px.

    max_non_rigid_reg_dim_px : int
        Resolution at which the non-rigid (optical-flow) warp is computed.
        VALIS default = 2 048 px. Higher → more accurate, much slower.

    thumbnail_size : int
        Size of the overview thumbnail used for initial coarse alignment.
        VALIS default = 512 px.

    align_to_reference : bool
        If True, the reference slide is held fixed and only the target is
        warped. If False, VALIS computes a consensus "average" space.
        Default = False (VALIS default).

    crop : str or None
        Post-registration crop strategy.
        None        → no crop (VALIS default)
        "reference" → crop to reference slide extent
        "overlap"   → crop to the overlapping region of all slides
        "all"       → crop to the union of all slides

    non_rigid_registrar_cls : object or None
        Non-rigid registrar *instance* (not class).
        Default = OpticalFlowWarper() — the VALIS library default.

    imgs_ordered : bool
        Whether slides are provided in serial-section order (z-stack).
        Default = False.

    micro_rigid_registrar_cls : object or None
        Optional micro-rigid registrar run *inside* register() for
        higher-resolution rigid refinement. Default = None (disabled).

    micro_rigid_registrar_params : dict
        Keyword arguments forwarded to micro_rigid_registrar_cls.

    run_register_micro : bool
        If True, runs a second non-rigid pass via register_micro() after
        the main register() call. Requires register_micro_dim_px >
        max_non_rigid_reg_dim_px. Default = False.

    register_micro_dim_px : int
        Resolution for the register_micro() pass. Must exceed
        max_non_rigid_reg_dim_px. Default = 4 096 px.

    max_acceptable_error_um : float or None
        If set, raises RuntimeError when the mean registration error
        (converted to µm) exceeds this threshold. Default = None (no check).
    """

    # ── Core resolution parameters ─────────────────────────────────────────
    max_processed_image_dim_px: int = 512  # default was 512
    max_non_rigid_reg_dim_px: int = (
        2048  # unchanged, used as it is mentioned in the research article
    )
    max_image_dim_px: int = 1024  # default was 1024
    thumbnail_size: int = 512  # default was 512

    # ── Registration behaviour ─────────────────────────────────────────────
    align_to_reference: bool = True  # VALIS default = False
    # norm_method:                  Optional[str]    = "img_stats"   # Valis Default = "Img_stats"
    crop: Optional[str] = "reference"  # None | "reference" | "overlap" | "all"
    non_rigid_registrar_cls: Optional[object] = None
    imgs_ordered: bool = False

    # ── Micro-rigid refinement (Mechanism 1 — inside register()) ──────────
    micro_rigid_registrar_cls: Optional[object] = None
    micro_rigid_registrar_params: dict = dataclasses.field(default_factory=dict)

    # ── Micro-rigid refinement (Mechanism 2 — post register_micro()) ──────
    run_register_micro: bool = False
    register_micro_dim_px: int = 4096  # must be > max_non_rigid_reg_dim_px

    # ── QC threshold ───────────────────────────────────────────────────────
    max_acceptable_error_um: Optional[float] = None

    def __post_init__(self) -> None:
        """Fill in the default non-rigid registrar instance if none was given.

        VALIS expects ``non_rigid_registrar_cls`` to be an *instance* of a
        non-rigid registrar (not the class itself), so this hook runs
        automatically after dataclass construction (per the standard
        ``__post_init__`` protocol) and assigns the library default —
        :class:`OpticalFlowWarper` — whenever the field was left at its
        default ``None`` and the VALIS import succeeded (i.e.
        ``OpticalFlowWarper is not None``). If VALIS is not installed,
        ``OpticalFlowWarper`` is itself ``None`` and this is a no-op,
        since VALIS-based registration would already be unavailable at
        that point.
        """
        # VALIS expects an *instance* of the non-rigid registrar, not the class.
        # Assign the library default (OpticalFlowWarper) when none is provided.
        if self.non_rigid_registrar_cls is None and OpticalFlowWarper is not None:
            self.non_rigid_registrar_cls = OpticalFlowWarper()


# ══════════════════════════════════════════════════════════════════════════════
# WSIRegistrar — main pipeline class
# ══════════════════════════════════════════════════════════════════════════════


class WSIRegistrar:
    """
    Registers a paired H&E + IHC whole-slide image (WSI) and extracts
    spatially aligned patch pairs.

    Workflow
    ────────
    1. Instantiate with slide paths and a config dict.
    2. Call ``register_slides()`` to run VALIS (or ORB fallback).
    3. Call ``generate_grid_map()`` to identify tissue-containing grid cells.
    4. Call ``extract_patch_pair()`` (or ``extract_single_patch()``) per grid cell.
    5. Call ``close()`` to release file handles and clean up temp files.

    Parameters
    ──────────
    path_ref : str
        Absolute path to the H&E (reference / fixed) slide.
    path_tgt : str or None
        Absolute path to the IHC (moving) slide.
        Pass None for reference-only (single-slide) mode.
    config : dict
        Pipeline configuration. Expected keys:
          - patch_size        : int   — patch edge length in pixels
          - grid_density      : int   — number of grid rows/cols
          - base_output_dir   : str   — root directory for all outputs
          - target_magnification : float — physical zoom for both slides (default 20x)
          - overlay_max_px    : int   — (optional) max edge for QC overlay images
          - orb_thumb_size    : int   — (optional) thumbnail size for ORB fallback
          - ransac_threshold  : float — (optional) RANSAC reprojection threshold
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
        self.config = config
        self.valis_cfg = valis_cfg or ValisConfig()

        # ── Slide paths ────────────────────────────────────────────────────
        self.path_ref = os.path.abspath(path_ref)
        self.path_tgt = os.path.abspath(path_tgt) if path_tgt else None

        # ── Registration state ─────────────────────────────────────────────
        self.method: Optional[str] = None  # "valis" | "orb"
        self.registration_ok: bool = False

        # VALIS objects (populated by _register_valis)
        self.valis_obj: Optional[object] = None  # registration.Valis instance
        self._registrar: Optional[object] = None  # alias for valis_obj; used by save_aligned_wsi()
        self._slide_ref_valis = None  # valis Slide (ref)
        self._slide_tgt_valis = None  # valis Slide (tgt)
        self.registration_error_df = None  # VALIS summary DataFrame

        # ORB fallback state (populated by _register_orb)
        self.orb_matrix = None  # 3×3 homography
        self.orb_scale: Optional[float] = None  # thumbnail → full-res scale factor
        self.orb_ref_scale_x: Optional[float] = None
        self.orb_ref_scale_y: Optional[float] = None
        self.orb_tgt_scale_x: Optional[float] = None
        self.orb_tgt_scale_y: Optional[float] = None

        # ── Open slides via OpenSlide ──────────────────────────────────────
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

        target_magnification = float(
            config.get("target_magnification", DEFAULT_TARGET_MAGNIFICATION)
        )
        ref_base, ref_source = objective_magnification_from_properties(
            self.slide_ref.properties,
            fallback=config.get("reference_source_magnification"),
        )
        self.ref_magnification_plan = build_magnification_plan(
            ref_base, target_magnification, self.slide_ref.level_downsamples
        )
        self.target_w, self.target_h = self.ref_magnification_plan.target_dimensions(
            self.slide_ref.dimensions
        )
        self.tgt_magnification_plan: Optional[MagnificationPlan] = None
        if self.slide_tgt is not None:
            tgt_base, tgt_source = objective_magnification_from_properties(
                self.slide_tgt.properties,
                fallback=config.get("target_source_magnification"),
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

        # Convenience name attributes
        self.ref_name = os.path.basename(self.path_ref)
        self.tgt_name = os.path.basename(self.path_tgt) if self.path_tgt else None
        self.base_name = os.path.splitext(self.ref_name)[0]

        # ── Output directory ───────────────────────────────────────────────
        item_name = config.get("output_item_name", self.base_name)
        self.output_dir = str(
            OutputLayout(config["base_output_dir"]).item_dir("alignment", item_name)
        )

        # ── Temp directory for VALIS intermediate files ────────────────────
        # Cleaned up automatically in close().
        self.temp_dir = tempfile.mkdtemp(prefix="valis_proc_")

    # ══════════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════════

    def register_slides(self, method: str = "valis") -> None:
        """
        Run slide registration.

        Parameters
        ──────────
        method : str
            "valis" — full rigid + non-rigid registration via the VALIS library.
            "orb"   — lightweight contour-shape-based affine registration
                      (stain-agnostic fallback; no VALIS required).

        Raises
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

    def generate_grid_map(self) -> Tuple[Image.Image, list]:
        """
        Divide the reference slide into a uniform grid and identify
        tissue-containing cells.

        Strategy
        ────────
        A low-resolution thumbnail is generated from the reference slide.
        Each grid cell is classified as "tissue" if more than 5 % of its
        pixels are darker than 230 in greyscale (i.e. not glass background).

        Returns
        ───────
        map_thumb : PIL.Image
            Thumbnail image saved to ``<output_dir>/grid_map.png``.
        valid_grids : list[int]
            Flat grid indices (row-major) of tissue-containing cells.
        """
        rows = cols = self.config["grid_density"]

        # Build a thumbnail that preserves the slide aspect ratio
        thumb_h = 1000
        thumb_w = int(thumb_h * (self.w / self.h))
        self.map_thumb = self.slide_ref.get_thumbnail((thumb_w, thumb_h))

        # Binary tissue mask: True where pixel is darker than 230 (tissue)
        mask = np.array(self.map_thumb.convert("L")) < 230

        step_y = mask.shape[0] / rows
        step_x = mask.shape[1] / cols
        self.valid_grids: list = []

        for idx in range(rows * cols):
            r, c = divmod(idx, cols)
            y1, y2 = int(r * step_y), int((r + 1) * step_y)
            x1, x2 = int(c * step_x), int((c + 1) * step_x)
            region = mask[y1:y2, x1:x2]
            tissue_fraction = np.count_nonzero(region) / region.size if region.size > 0 else 0
            if tissue_fraction > 0.05:
                self.valid_grids.append(idx)

        # self.map_thumb.save(os.path.join(self.output_dir, "grid_map.png"))
        logger.info(f"[GRID] {len(self.valid_grids)} tissue grids out of {rows * cols} total.")
        return self.map_thumb, self.valid_grids

    def extract_patch_pair(self, grid_id: int) -> int:
        """
        Extract spatially aligned H&E / IHC patch pairs from a single grid cell.

        For each non-background patch in the reference (H&E) slide, the
        corresponding IHC location is computed via ``_transform_coords()``
        and both patches are saved as matching PNG files.

        Reference and moving PNGs are written together inside the case output
        directory. Filenames contain grid, patch, and channel identifiers.

        Parameters
        ──────────
        grid_id : int
            Flat (row-major) grid index, as returned by ``generate_grid_map()``.

        Returns
        ───────
        count : int
            Number of patch pairs successfully saved.
        """
        rows = cols = self.config["grid_density"]
        patch_size = self.config["patch_size"]
        ref_stem = os.path.splitext(self.ref_name)[0]

        # Compute the base-level pixel extent of this grid cell
        real_sx = self.target_w / cols
        real_sy = self.target_h / rows
        r, c = divmod(grid_id, cols)
        min_x, min_y = int(c * real_sx), int(r * real_sy)
        max_x, max_y = int(min_x + real_sx), int(min_y + real_sy)

        count = 0
        for y in range(min_y, max_y, patch_size):
            for x in range(min_x, max_x, patch_size):
                # Skip incomplete border patches (avoids partial-tissue artefacts)
                if x + patch_size > max_x or y + patch_size > max_y:
                    continue

                # Read H&E patch
                x0, y0 = self.ref_magnification_plan.target_to_level0((x, y))
                patch_ref = self._read_exact_magnification(
                    self.slide_ref,
                    self.ref_magnification_plan,
                    (x0, y0),
                    (patch_size, patch_size),
                ).convert("RGB")

                # Skip near-white (glass background) patches — mean > 240 ≈ background
                if np.asarray(patch_ref).mean() > 240:
                    continue

                # Map H&E coordinates → IHC coordinates
                tx, ty = self._transform_coords(x0, y0)
                if tx is None:
                    continue

                # Read IHC patch at the mapped location
                try:
                    patch_tgt = self._read_exact_magnification(
                        self.slide_tgt,
                        self.tgt_magnification_plan,
                        (tx, ty),
                        (patch_size, patch_size),
                    ).convert("RGB")
                except Exception:
                    continue

                # Skip IHC patch if it is also background
                if np.asarray(patch_tgt).mean() > 240:
                    continue

                # Save matched pair
                count += 1
                stem = f"{ref_stem}_grid{grid_id:03d}_patch{count:04d}"
                patch_ref.save(os.path.join(self.output_dir, f"{stem}_reference.png"))
                patch_tgt.save(os.path.join(self.output_dir, f"{stem}_moving.png"))

        return count

    def extract_single_patch(self, grid_id: int) -> int:
        """
        Extract patches from the reference slide only (no IHC target).

        Useful for reference-only mode or when only H&E patches are needed.
        Patches are saved directly inside the case output directory with the
        grid identifier encoded in each filename.

        Parameters
        ──────────
        grid_id : int
            Flat (row-major) grid index.

        Returns
        ───────
        count : int
            Number of patches saved.
        """
        rows = cols = self.config["grid_density"]
        patch_size = self.config["patch_size"]
        ref_stem = os.path.splitext(self.ref_name)[0]

        real_sx = self.target_w / cols
        real_sy = self.target_h / rows
        r, c = divmod(grid_id, cols)
        min_x, min_y = int(c * real_sx), int(r * real_sy)
        max_x, max_y = int(min_x + real_sx), int(min_y + real_sy)

        count = 0
        for y in range(min_y, max_y, patch_size):
            for x in range(min_x, max_x, patch_size):
                if x + patch_size > max_x or y + patch_size > max_y:
                    continue
                location0 = self.ref_magnification_plan.target_to_level0((x, y))
                patch = self._read_exact_magnification(
                    self.slide_ref,
                    self.ref_magnification_plan,
                    location0,
                    (patch_size, patch_size),
                ).convert("RGB")
                if np.asarray(patch).mean() > 240:
                    continue
                count += 1
                patch.save(
                    os.path.join(
                        self.output_dir,
                        f"{ref_stem}_grid{grid_id:03d}_patch{count:04d}.png",
                    )
                )

        return count

    @staticmethod
    def _read_exact_magnification(
        slide: object,
        plan: MagnificationPlan,
        location0: Tuple[int, int],
        output_size: Tuple[int, int],
    ) -> Image.Image:
        """Read a level-0 location and return pixels at the plan's exact zoom."""
        native_size = plan.native_read_size(output_size)
        image = slide.read_region(location0, plan.level, native_size)
        if image.size != output_size:
            image = image.resize(output_size, Image.Resampling.LANCZOS)
        return image

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

        # Remove VALIS temp files (feature maps, warped thumbnails, etc.)
        if os.path.isdir(self.temp_dir):
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

        self.valis_obj = registration.Valis(
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
        )

        logger.info("[VALIS] Running registration (rigid + non-rigid)...")
        rigid_reg, non_rigid_reg, error_df = self.valis_obj.register()

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
                    max_non_rigid_registration_dim_px=cfg.register_micro_dim_px
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

    def _check_registration_quality(self, error_df) -> None:
        """
        Log VALIS registration error and optionally raise if it exceeds the
        configured threshold.

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
                # Scale from processed-resolution pixels → full-resolution µm
                scale = self.w / self.valis_cfg.max_processed_image_dim_px
                res_um_per_px = res.mean()
                mean_err_um = mean_err * scale * res_um_per_px
                logger.info(
                    f"[QC] Mean registration error: "
                    f"{mean_err:.2f} px (processed)  ≈  {mean_err_um:.2f} µm"
                )
                unit = "µm"
                mean_err = mean_err_um
            else:
                logger.info(f"[QC] Mean registration error: {mean_err:.2f} {unit}")

        # Enforce threshold if configured
        threshold = self.valis_cfg.max_acceptable_error_um
        if threshold is not None and unit == "µm" and mean_err > threshold:
            raise RuntimeError(
                f"[QC] Registration error {mean_err:.2f} µm exceeds "
                f"threshold {threshold} µm. Aborting patch extraction."
            )

        error_df.to_csv(csv_path, index=False)
        logger.info(f"[QC] Registration summary saved → {csv_path}")

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
                """
                Return a warped RGB image from the highest-resolution pyramid
                level that fits within TARGET_MAX_PX on its longest edge.

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
                """
                Return a binary mask where 255 = background (glass), 0 = tissue.
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

    def save_aligned_wsi(
        self,
        level: int = 0,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Save the aligned (warped) target WSI to disk.

        Dispatches to the appropriate save strategy based on the registration
        method used (``self.method``).

        ----------
        After registration, the target (IHC) slide must be warped into the
        coordinate space of the reference (H&E) slide before patches can be
        meaningfully compared or extracted.

        VALIS
        ----------
        Applies the full rigid + non-rigid VALIS transformation pipeline to the
        target slide and saves the result as a pyramidal OME-TIFF, which is
        immediately usable in QuPath, ImageScope, or downstream pipelines.

        Algorithm:
        1. Retrieve the target slide object from the VALIS registrar using
        the absolute path to the IHC file (``self.path_tgt``).
        2. Resolve the output file path, defaulting to
        ``<output_dir>/<tgt_stem>_aligned_level<level>.ome.tiff``.
        3. Call ``Slide.warp_and_save_slide()`` on the target slide object,
        which tiles and warps the slide at the requested pyramid level
        and writes a pyramidal OME-TIFF to disk.

        Output format:
        - Format  : OME-TIFF (pyramidal, tiled)
        - Warping : rigid + non-rigid (full VALIS transformation)
        - Crop    : cropped to the overlap region of both slides

        ORB
        --------
        Applies the affine matrix estimated during contour-shape registration
        tile-by-tile, avoiding loading the full WSI into RAM. The affine is
        inverted from reference-to-target into target-to-reference space and
        scaled independently for both slide pyramids. Then
        each output tile is back-projected to locate the corresponding IHC
        source region, which is read via OpenSlide and warped with
        ``cv2.warpAffine``. Each completed tile is written to a temporary VIPS
        image, and libvips lazily joins those disk-backed tiles while writing
        the final pyramidal OME-TIFF. ORB export never imports VALIS.

        Algorithm:
        1. Compose the target-level to reference-level affine from thumbnail
        scales, pyramid downsamples, and the inverse ORB matrix.
        2. Pre-compute the inverse affine once for back-projecting tile corners.
        3. Iterate over TILExTILE output tiles; for each tile, back-project its
        corners to find the IHC source bounding box, read that region via
        OpenSlide, apply a locally translated affine, and persist that bounded
        tile to a temporary VIPS image.
        4. Lazily join the tile files without materializing the level-sized
        image in NumPy.
        5. Attach reference-space physical-pixel metadata and stream the
        pyramidal OME-TIFF via libvips.

        Output format:
        - Format      : OME-TIFF (pyramidal, tiled, pyvips-written)
        - Warping     : rigid affine only (ORB contour-shape registration)
        - Compression : deflate (lossless)
        - Metadata    : RGB OME-XML with reference-space physical pixel size

        Shared parameters
        -----------------
        level : int
            Pyramid level to warp and save.
            0 = full resolution, 1 = half res, 2 = quarter res, etc.
            Level 0 is very large — use level 1 or 2 unless full resolution
            is required. For VALIS, level 1 is recommended. ORB memory remains
            bounded at every level; level 0 still requires the most I/O and
            temporary disk space.

        output_path : str, optional
            Full destination file path. Auto-generated when None:
            - VALIS : ``<output_dir>/<tgt_stem>_aligned_level-<level>.ome.tiff``
            - ORB   : ``<output_dir>/<tgt_stem>_aligned_orb_level-<level>.ome.tiff``

        Returns
        -------
        str or None
            Absolute path to the saved file on success, or None on failure.
        """

        # ══════════════════════════════════════════════════════════════════════
        # VALIS
        # ══════════════════════════════════════════════════════════════════════
        if self.method == "valis":
            if self._registrar is None:
                logger.error("[ERROR] save_aligned_wsi: VALIS registrar not initialized.")
                return None

            try:
                tgt_key = os.path.basename(self.path_tgt)
                tgt_slide_obj = self._registrar.get_slide(tgt_key)
                if tgt_slide_obj is None:
                    tgt_slide_obj = self._registrar.get_slide(self.path_tgt)
                if tgt_slide_obj is None:
                    logger.error(
                        f"[ERROR] Could not find target slide '{tgt_key}' in VALIS registrar."
                    )
                    logger.debug(
                        f"[DEBUG] Available slides: {[s.name for s in self._registrar.slide_dict.values()]}"
                    )
                    return None
            except Exception as e:
                logger.error(f"[ERROR] Could not find target slide in VALIS registrar: {e}")
                return None

            if output_path is None:
                tgt_stem = os.path.splitext(os.path.basename(self.path_tgt))[0]
                output_path = os.path.join(
                    self.output_dir, f"{tgt_stem}_aligned_level-{level}.ome.tiff"
                )
            output_path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            try:
                logger.info(f"[SAVE] Warping and saving ONLY target slide: {tgt_slide_obj.name}")
                logger.info(f"[SAVE] Level: {level} | Output: {output_path}")

                warped_slide = tgt_slide_obj.warp_slide(level=level, non_rigid=True, crop=True)
                out_shape_wh = warp_tools.get_shape(warped_slide)[0:2][::-1]
                tile_wh = slide_io.get_tile_wh(
                    reader=tgt_slide_obj.reader, level=level, out_shape_wh=out_shape_wh
                )

                tgt_slide_obj.warp_and_save_slide(
                    dst_f=output_path,
                    level=level,
                    src_f=tgt_slide_obj.src_f,
                    crop=True,
                    pyramid=True,
                    tile_wh=tile_wh,
                )
                logger.info(f"[SAVE] Successfully saved aligned target → {output_path}")
                return output_path

            except Exception as exc:
                logger.error(f"[ERROR] save_aligned_wsi() failed during warp_and_save: {exc}")
                import traceback

                traceback.print_exc()
                return None

        # ══════════════════════════════════════════════════════════════════════
        # ORB
        # ══════════════════════════════════════════════════════════════════════
        elif self.method == "orb":
            if self.orb_matrix is None:
                logger.error(
                    "[ERROR] save_aligned_wsi: ORB matrix not set. Run register_slides() first."
                )
                return None

            # ── 1. Resolve output path ────────────────────────────────────────
            if output_path is None:
                tgt_stem = os.path.splitext(os.path.basename(self.path_tgt))[0]
                output_path = os.path.join(
                    self.output_dir, f"{tgt_stem}_aligned_orb_level-{level}.ome.tiff"
                )
            output_path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            return self._save_orb_streamed(level, output_path)

        else:
            logger.error(f"[ERROR] save_aligned_wsi: unknown registration method '{self.method}'.")
            return None

    def _orb_affine_for_level(self, output_level: int, source_level: int) -> np.ndarray:
        """Return the target-level to reference-level ORB affine.

        ``orb_matrix`` maps reference-thumbnail coordinates to the resized
        target-thumbnail coordinates. Saving an aligned target requires the
        inverse mapping, with independent reference/target pixel scales and
        pyramid downsamples folded into the homogeneous transform.
        """
        if self.orb_matrix is None:
            raise RuntimeError("ORB matrix is unavailable; run register_slides('orb') first")
        scales = (
            self.orb_ref_scale_x,
            self.orb_ref_scale_y,
            self.orb_tgt_scale_x,
            self.orb_tgt_scale_y,
        )
        if any(value is None or value <= 0 for value in scales):
            raise RuntimeError("ORB thumbnail scales are unavailable")

        ref_ds = float(self.slide_ref.level_downsamples[output_level])
        tgt_ds = float(self.slide_tgt.level_downsamples[source_level])
        ref_thumb_to_full = np.diag([self.orb_ref_scale_x, self.orb_ref_scale_y, 1.0])
        tgt_full_to_thumb = np.diag([1.0 / self.orb_tgt_scale_x, 1.0 / self.orb_tgt_scale_y, 1.0])
        output_from_ref_full = np.diag([1.0 / ref_ds, 1.0 / ref_ds, 1.0])
        tgt_full_from_source = np.diag([tgt_ds, tgt_ds, 1.0])
        return (
            output_from_ref_full
            @ ref_thumb_to_full
            @ np.linalg.inv(self.orb_matrix)
            @ tgt_full_to_thumb
            @ tgt_full_from_source
        )

    @staticmethod
    def _rgb_ome_xml(
        width: int,
        height: int,
        name: str,
        mpp_x: Optional[float],
        mpp_y: Optional[float],
    ) -> str:
        """Build minimal valid OME-XML for one interleaved RGB image."""
        namespace = "http://www.openmicroscopy.org/Schemas/OME/2016-06"
        ET.register_namespace("", namespace)
        ome = ET.Element(f"{{{namespace}}}OME")
        image = ET.SubElement(ome, f"{{{namespace}}}Image", ID="Image:0", Name=name)
        attrs = {
            "ID": "Pixels:0",
            "DimensionOrder": "XYCZT",
            "Type": "uint8",
            "SizeX": str(width),
            "SizeY": str(height),
            "SizeC": "3",
            "SizeZ": "1",
            "SizeT": "1",
            "Interleaved": "true",
        }
        if mpp_x and mpp_x > 0:
            attrs.update(PhysicalSizeX=str(mpp_x), PhysicalSizeXUnit="µm")
        if mpp_y and mpp_y > 0:
            attrs.update(PhysicalSizeY=str(mpp_y), PhysicalSizeYUnit="µm")
        pixels = ET.SubElement(image, f"{{{namespace}}}Pixels", attrs)
        ET.SubElement(
            pixels,
            f"{{{namespace}}}Channel",
            ID="Channel:0:0",
            Name="RGB",
            SamplesPerPixel="3",
        )
        ET.SubElement(pixels, f"{{{namespace}}}TiffData")
        return ET.tostring(ome, encoding="unicode", xml_declaration=True)

    def _save_orb_streamed(self, level: int, output_path: str) -> str:
        """Warp ORB output through bounded tiles and stream it with libvips.

        Every warped tile is materialized to a temporary VIPS image. The final
        mosaic remains a lazy libvips graph during pyramidal TIFF generation,
        so memory is bounded by the configured tile and libvips cache sizes
        rather than the level-0 slide dimensions.
        """
        if not HAS_PYVIPS:
            raise ImportError(
                "ORB aligned-WSI export requires pyvips/libvips. Install 'rocqipath[orb]'."
            )
        if self.slide_tgt is None:
            raise RuntimeError("ORB aligned-WSI export requires a target slide")
        if not 0 <= level < len(self.slide_ref.level_dimensions):
            raise ValueError(f"Invalid reference pyramid level: {level}")

        out_w, out_h = self.slide_ref.level_dimensions[level]
        ref_ds = float(self.slide_ref.level_downsamples[level])
        if hasattr(self.slide_tgt, "get_best_level_for_downsample"):
            source_level = int(self.slide_tgt.get_best_level_for_downsample(ref_ds))
        else:
            source_level = min(level, len(self.slide_tgt.level_dimensions) - 1)
        source_w, source_h = self.slide_tgt.level_dimensions[source_level]
        source_ds = float(self.slide_tgt.level_downsamples[source_level])
        affine = self._orb_affine_for_level(level, source_level)
        inverse = np.linalg.inv(affine)

        tile_size = max(64, int(self.config.get("orb_save_tile_size", 1024)))
        tiles_x = (out_w + tile_size - 1) // tile_size
        tiles_y = (out_h + tile_size - 1) // tile_size
        logger.info(
            "[ORB SAVE] Streaming {}x{} output in {} tiles (ref L{}, target L{})",
            out_w,
            out_h,
            tiles_x * tiles_y,
            level,
            source_level,
        )

        with tempfile.TemporaryDirectory(prefix="rocqipath_orb_tiles_") as tile_dir:
            tile_paths = []
            with tqdm(
                total=tiles_x * tiles_y,
                desc="[ORB SAVE] Warping tiles",
                unit="tile",
                leave=True,
                dynamic_ncols=True,
            ) as progress:
                for row in range(tiles_y):
                    for col in range(tiles_x):
                        ox, oy = col * tile_size, row * tile_size
                        width = min(tile_size, out_w - ox)
                        height = min(tile_size, out_h - oy)
                        corners = np.array(
                            [
                                [ox, oy, 1],
                                [ox + width, oy, 1],
                                [ox, oy + height, 1],
                                [ox + width, oy + height, 1],
                            ],
                            dtype=np.float64,
                        ).T
                        source_corners = inverse @ corners
                        source_corners /= source_corners[2]
                        margin = 2
                        sx1 = max(0, int(np.floor(source_corners[0].min())) - margin)
                        sy1 = max(0, int(np.floor(source_corners[1].min())) - margin)
                        sx2 = min(source_w, int(np.ceil(source_corners[0].max())) + margin)
                        sy2 = min(source_h, int(np.ceil(source_corners[1].max())) + margin)

                        tile = np.full((tile_size, tile_size, 3), 255, dtype=np.uint8)
                        if sx2 > sx1 and sy2 > sy1:
                            patch = self.slide_tgt.read_region(
                                (int(round(sx1 * source_ds)), int(round(sy1 * source_ds))),
                                source_level,
                                (sx2 - sx1, sy2 - sy1),
                            ).convert("RGB")
                            local = affine[:2].copy()
                            local[:, 2] += affine[:2, :2] @ np.array(
                                [sx1, sy1], dtype=np.float64
                            ) - np.array([ox, oy], dtype=np.float64)
                            tile[:height, :width] = cv2.warpAffine(
                                np.asarray(patch),
                                local,
                                (width, height),
                                flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT,
                                borderValue=(255, 255, 255),
                            )
                            patch.close()

                        tile_path = os.path.join(tile_dir, f"tile_{row:06d}_{col:06d}.v")
                        pyvips.Image.new_from_memory(
                            tile.tobytes(), tile_size, tile_size, 3, "uchar"
                        ).write_to_file(tile_path)
                        tile_paths.append(tile_path)
                        progress.update(1)

            tile_images = [
                pyvips.Image.new_from_file(path, access="sequential") for path in tile_paths
            ]
            mosaic = pyvips.Image.arrayjoin(tile_images, across=tiles_x).crop(0, 0, out_w, out_h)

            # Output pixels live in the reference coordinate system.
            properties = getattr(self.slide_ref, "properties", {})
            try:
                base_mpp_x = float(properties.get("openslide.mpp-x", 0.0))
                base_mpp_y = float(properties.get("openslide.mpp-y", 0.0))
            except (TypeError, ValueError):
                base_mpp_x = base_mpp_y = 0.0
            mpp_x = base_mpp_x * ref_ds if base_mpp_x > 0 else None
            mpp_y = base_mpp_y * ref_ds if base_mpp_y > 0 else None
            resolution = {}
            if mpp_x and mpp_y:
                resolution = {"xres": 1000.0 / mpp_x, "yres": 1000.0 / mpp_y}
            mosaic = mosaic.copy(**resolution)
            ome_xml = self._rgb_ome_xml(out_w, out_h, os.path.basename(output_path), mpp_x, mpp_y)
            mosaic.set_type(pyvips.GValue.gstr_type, "image-description", ome_xml)
            mosaic.tiffsave(
                output_path,
                tile=True,
                tile_width=512,
                tile_height=512,
                pyramid=True,
                subifd=True,
                compression="deflate",
                bigtiff=True,
            )

        logger.info("[ORB SAVE] Saved streamed aligned WSI → {}", output_path)
        return output_path

    # ══════════════════════════════════════════════════════════════════════════
    # ORB / contour-shape registration
    # ══════════════════════════════════════════════════════════════════════════
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
        def _to_od_channel(rgb: np.ndarray) -> np.ndarray:
            """
            Convert RGB → optical density, return the per-pixel maximum OD value.

            OD = -log(I / I_max).  The maximum across R/G/B channels corresponds
            to the most-absorbing stain at each pixel, giving a tissue-presence
            signal that is independent of stain colour (H&E, DAB, Meca79, CD31…).

            Parameters
            ----------
            rgb : np.ndarray, shape (H, W, 3), dtype uint8

            Returns
            -------
            od_max : np.ndarray, shape (H, W), dtype float32
                Values nominally in [0, ~3]; background ≈ 0, dense tissue ≈ 0.5–2.
            """
            rgb_f = np.clip(rgb.astype(np.float32), 1.0, 255.0)
            od = -np.log(rgb_f / 255.0)  # shape (H, W, 3)
            return np.max(od, axis=2)  # shape (H, W)

        def _tissue_mask_od(rgb: np.ndarray) -> np.ndarray:
            """
            Binary tissue mask via Otsu thresholding on the OD max-channel.

            Returns
            -------
            mask : np.ndarray, shape (H, W), dtype uint8
                255 = tissue, 0 = background.
            """
            od = _to_od_channel(rgb)
            od_u8 = np.uint8(np.clip(od * 85.0, 0, 255))  # scale [0,~3] → [0,255]
            _, mask = cv2.threshold(od_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=3)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=2)
            return mask

        def _phase_correlation_translation(
            gray_ref: np.ndarray,
            gray_tgt: np.ndarray,
        ) -> tuple[float, float]:
            """
            Estimate a pure (dx, dy) translation between two grayscale images using
            normalised FFT phase correlation.

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
            """
            Return the N largest external contours that exceed min_area_frac of the
            total image area.  Slide labels and small artefacts are filtered out.
            """
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            min_area = mask.shape[0] * mask.shape[1] * min_area_frac
            cnts = [c for c in cnts if cv2.contourArea(c) > min_area]
            return sorted(cnts, key=cv2.contourArea, reverse=True)[:n]

        def _contour_features(
            cnt: np.ndarray,
            img_shape: tuple[int, int],
        ) -> np.ndarray:
            """
            Compute a 4-D feature vector for a contour that combines shape statistics
            with normalised spatial position.

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
            """
            Estimate a 2×3 affine matrix from matched contour centroids,
            with a clear degradation ladder:

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
            """
            Refine a coarse 3x3 affine matrix by estimating the residual translation
            on a higher-resolution thumbnail pair.

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

            ref_hi = np.array(
                self.slide_ref.get_thumbnail((rtw, rth)).convert("L"), dtype=np.float32
            )
            tgt_hi = np.array(
                self.slide_tgt.get_thumbnail((rtw, rth)).convert("L"), dtype=np.float32
            )
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
            """
            Save a false-colour registration QC overlay:
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
            logger.info(
                f"[ORB] Reshaped target RGB thumbnail from {tgt_w}x{tgt_h} to {ref_w}x{ref_h}"
            )
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
            logger.warning(
                f"[ORB] WARNING: NCC {ncc:.4f} < threshold {MIN_NCC}. Registration flagged."
            )
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

    # ══════════════════════════════════════════════════════════════════════════
    # coordinate transform
    # ══════════════════════════════════════════════════════════════════════════

    def _transform_coords(self, x: int, y: int) -> Tuple[Optional[int], Optional[int]]:
        """
        Map a base-level (x, y) coordinate from the reference slide to the
        corresponding location in the target slide.

        VALIS path
        ──────────
        Calls ``Slide.warp_xy_from_to()``, which applies the full rigid +
        non-rigid transform chain from ref → tgt in base-level pixel
        coordinates. This is the correct per-slide API (not ``Valis.warp_xy``).

        ORB path
        ────────
        Scales the coordinate down to thumbnail space, applies the 3x3
        homography estimated by ``_register_orb()``, then scales back to
        base-level coordinates.

        Parameters
        ──────────
        x, y : int
            Base-level pixel coordinates in the reference slide.

        Returns
        ───────
        (tx, ty) : (int, int) or (None, None)
            Corresponding base-level coordinates in the target slide.
            Returns (None, None) on failure.
        """
        if self.method == "valis" and self._slide_ref_valis is not None:
            try:
                coords = np.array([[x, y]], dtype=float)
                warped = self._slide_ref_valis.warp_xy_from_to(coords, self._slide_tgt_valis)
                return int(warped[0, 0]), int(warped[0, 1])
            except Exception as exc:
                logger.warning(f"[WARN] warp_xy_from_to failed at ({x},{y}): {exc}")
                return None, None

        elif self.method == "orb" and self.orb_matrix is not None:
            scales = (
                self.orb_ref_scale_x,
                self.orb_ref_scale_y,
                self.orb_tgt_scale_x,
                self.orb_tgt_scale_y,
            )
            if any(value is None or value <= 0 for value in scales):
                return None, None
            # Reference full-res → shared thumbnail → target full-res.
            pt = np.array(
                [[[x / self.orb_ref_scale_x, y / self.orb_ref_scale_y]]],
                dtype=np.float32,
            )
            pt_t = cv2.perspectiveTransform(pt, self.orb_matrix)
            return (
                int(pt_t[0, 0, 0] * self.orb_tgt_scale_x),
                int(pt_t[0, 0, 1] * self.orb_tgt_scale_y),
            )

        return None, None
