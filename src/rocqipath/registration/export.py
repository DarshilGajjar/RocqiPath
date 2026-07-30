"""Aligned-slide export for VALIS and streamed ORB transforms."""

from __future__ import annotations

import os
import tempfile
from typing import Optional

import cv2
import numpy as np
from tqdm.auto import tqdm

from rocqipath.core.logging import logger
from rocqipath.utils.vips import rgb_ome_xml

try:
    import pyvips

    HAS_PYVIPS = True
except (ImportError, OSError):
    pyvips = None
    HAS_PYVIPS = False

try:
    from valis import slide_io, warp_tools
except (ImportError, OSError):
    slide_io = warp_tools = None


class RegistrationExportMixin:
    """Methods mixed into :class:`WSIRegistrar`."""

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
        return rgb_ome_xml(width, height, name, mpp_x, mpp_y)

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
