"""Orchestrate discovery, registration, export, and optional QC for WSI pairs."""

from __future__ import annotations

import inspect
import re
import traceback
import warnings
from pathlib import Path
from typing import Any, List, Union

from rocqipath.config import AlignmentConfig
from rocqipath.core.logging import logger
from rocqipath.core.output import OutputLayout
from rocqipath.registration.models import AlignedCaseResult, CaseContext
from rocqipath.registration.quality import qc_center_patch_side_by_side
from rocqipath.utils.discovery import (
    build_sample_pairs,
    discover_pair_folders,
    ensure_directory,
    index_pair_folder,
    is_wsi_file as is_wsi_file,
    list_wsi_files as _list_wsi_files,
)
from rocqipath.utils.naming import build_filename_pattern, parse_wsi_filename

__all__ = [
    "AlignmentConfig",
    "CaseContext",
    "AlignedCaseResult",
    "build_filename_pattern",
    "discover_pair_folders",
    "list_wsi_files",
    "parse_wsi_filename",
    "index_pair_folder",
    "build_sample_pairs",
    "qc_center_patch_side_by_side",
    "AlignmentProcessor",
    "run_alignment",
]


try:
    from tqdm.auto import tqdm
except ImportError:

    def tqdm(iterable, *args, **kwargs):  # type: ignore[misc]
        """No-op fallback for :func:`tqdm.auto.tqdm` when tqdm isn't installed.

        Returns ``iterable`` unchanged, so any code written as
        ``for x in tqdm(items):`` continues to work identically — just
        without a progress bar — when the optional ``tqdm`` dependency
        is absent.

        Parameters
        ----------
        iterable : Iterable
            The iterable that would normally be wrapped with a progress
            bar.
        *args, **kwargs
            Accepted and ignored, matching tqdm's permissive signature
            (e.g. ``desc=``, ``total=``) so call sites don't need to
            special-case the fallback.

        Returns
        -------
        Iterable
            ``iterable``, unmodified.
        """
        return iterable


try:
    from rocqipath.core.console import print_banner as _print_banner

    _print_banner()
except Exception:
    pass


try:
    from rocqipath.registration.registrar import ValisConfig, WSIRegistrar

    WSI_PROCESSING_AVAILABLE = True
except ImportError:
    WSIRegistrar = None  # type: ignore[assignment,misc]
    ValisConfig = None  # type: ignore[assignment,misc]
    WSI_PROCESSING_AVAILABLE = False
    warnings.warn(
        "rocqipath.registration.registrar not found. "
        "Set dry_run=True to test slide pairing without running registration.",
        stacklevel=2,
    )


DEFAULT_REFERENCE_NAME: str = "reference"


DEFAULT_MOVING_NAME: str = "moving"


DEFAULT_FILENAME_PATTERN: str = build_filename_pattern()


def list_wsi_files(directory: Union[str, Path]) -> List[str]:
    """List direct-child WSIs in the alignment pipeline's casefold order."""
    return _list_wsi_files(directory, recursive=False, sort_mode="casefold")


class AlignmentProcessor:
    """Orchestrate slide pairing, registration, export, and optional QC.

    Parameters
    ----------
    config : AlignmentConfig
        Typed configuration object.  Use :func:`run_alignment` as the
        normal entry point rather than instantiating this class directly.

    Attributes
    ----------
    pair_folders : List[str]
        Pair-folder names that will be processed (after auto-discovery
        if ``config.pair_folders`` is empty).
    """

    def __init__(self, config: AlignmentConfig) -> None:
        """Resolve directories, compile the filename pattern, and discover pair folders.

        Parameters
        ----------
        config : AlignmentConfig
            Typed configuration object — see the class docstring above.
            Stored on ``self.cfg`` for later use by :meth:`align_case`
            and :meth:`run`.

        Notes
        -----
        Construction performs real filesystem work, not just attribute
        assignment:

        - ``config.input_dir`` is resolved via :func:`ensure_directory`
          with ``create=False`` — it must already exist, or this raises
          :class:`FileNotFoundError`.
        - ``config.output_dir`` is resolved via :func:`ensure_directory`
          with ``create=True`` — it is created if missing.
        - ``config.filename_pattern`` is compiled once into
          ``self._pattern`` (already resolved and validated for its
          required named groups by
          :meth:`AlignmentConfig.__post_init__`, so no further
          validation happens here).
        - ``self.pair_folders`` is resolved from
          ``config.pair_folders`` if non-empty, otherwise
          auto-discovered by scanning ``self.input_dir`` via
          :func:`discover_pair_folders`, using
          ``config.reference_name``/``config.moving_name`` as the
          expected subfolder names. If neither yields any folders,
          a warning is logged (not an error — an empty
          ``self.pair_folders`` list means :meth:`run` will simply process
          zero cases).
        """
        self.cfg = config

        self.input_dir = ensure_directory(config.input_dir, create=False)
        self.output_dir = ensure_directory(config.output_dir, create=True)

        # Compile filename pattern once
        self._pattern = re.compile(config.filename_pattern, re.IGNORECASE)

        # Resolve pair-folder list
        configured = config.pair_folders or []
        self.pair_folders: List[str] = (
            configured
            if configured
            else discover_pair_folders(self.input_dir, config.reference_name, config.moving_name)
        )
        if not self.pair_folders:
            logger.warning(
                "No alignment pair folders found under: %s\n"
                "Each pair folder must have a '%s/' and/or '%s/' subdirectory.",
                self.input_dir,
                config.reference_name,
                config.moving_name,
            )

    # ── internal helpers ──────────────────────────────────────────────────────

    def _make_valis_config(self) -> Any:
        """Build a ``ValisConfig`` from this processor's ``AlignmentConfig``.

        Currently forwards only ``valis_max_error_um`` — the rest of
        ``ValisConfig``'s fields are left at their library defaults. Used
        internally by :meth:`align_case` when constructing each
        :class:`~rocqipath.registration.registrar.WSIRegistrar`.

        Returns
        -------
        ValisConfig
            A config instance with ``max_acceptable_error_um`` set from
            ``self.cfg.valis_max_error_um``.

        Raises
        ------
        RuntimeError
            If :mod:`rocqipath.registration.registrar` (and therefore VALIS)
            is not installed. Callers should either install the
            ``valis``/``wsi`` extra or set ``dry_run=True`` on the
            ``AlignmentConfig`` to skip real registration entirely.
        """
        if not WSI_PROCESSING_AVAILABLE:
            raise RuntimeError(
                "rocqipath.registration.registrar is not installed. "
                "Install the package or set dry_run=True."
            )
        candidate = {
            "max_acceptable_error_um": self.cfg.valis_max_error_um,
            # "max_processed_image_dim_px": self.cfg.valis_processed_dim,
            "max_non_rigid_reg_dim_px": self.cfg.valis_non_rigid_dim,
            "feature_detector": self.cfg.valis_feature_detector,
            "num_features": self.cfg.valis_num_features,
            "check_for_reflections": self.cfg.valis_check_reflections,
            "norm_method": self.cfg.valis_norm_method,
        }

        # Only pass fields this ValisConfig actually defines, so an older core
        # degrades to its defaults with a clear warning instead of TypeError.
        try:
            accepted = set(inspect.signature(ValisConfig).parameters)
        except (TypeError, ValueError):
            accepted = set(candidate)
        rejected = sorted(k for k in candidate if k not in accepted)
        if rejected:
            logger.warning(
                f"ValisConfig does not accept {rejected} — those registration "
                f"settings will not take effect. Update "
                f"rocqipath.registration.registrar."
            )
        return ValisConfig(**{k: v for k, v in candidate.items() if k in accepted})

    def _make_registrar_cfg(self, output_root: Path, item_name: str) -> dict:
        """Build the plain-dict config expected by ``WSIRegistrar``'s constructor.

        Parameters
        ----------
        output_root : Path
            User-selected root beneath which the alignment module directory is created.
        item_name : str
            Per-case folder name beneath ``alignment``.

        Returns
        -------
        dict
            A dict with keys ``"patch_size"``, ``"grid_density"``,
            ``"base_output_dir"`` (as a string), and
            physical magnification fields populated from ``self.cfg``. See
            :class:`~rocqipath.registration.registrar.WSIRegistrar` for the
            full set of keys it accepts — this helper supplies only the
            subset ``AlignmentConfig`` exposes.
        """
        return {
            "patch_size": self.cfg.patch_size,
            "grid_density": self.cfg.grid_density,
            "base_output_dir": str(output_root),
            "output_item_name": item_name,
            "target_magnification": self.cfg.target_magnification,
            "reference_source_magnification": self.cfg.reference_source_magnification,
            "moving_source_magnification": self.cfg.moving_source_magnification,
            "max_physical_field_ratio": self.cfg.max_physical_field_ratio,
            "keep_valis_diagnostics": self.cfg.keep_valis_diagnostics,
        }

    # ── per-case alignment ────────────────────────────────────────────────────

    def align_case(
        self,
        case: CaseContext,
        output_root: Union[str, Path],
    ) -> AlignedCaseResult:
        """
        Register one reference/moving pair and save the aligned moving WSI.

        Parameters
        ----------
        case : CaseContext
        output_root : str or Path
            Alignment output root; the case subfolder is
            created inside it by ``WSIRegistrar``.

        Returns
        -------
        AlignedCaseResult
            Contains the registrar, grid thumbnail, tissue grid list, and
            path to the saved aligned moving OME-TIFF.
        """
        if self.cfg.dry_run:
            return AlignedCaseResult(case=case, registrar=None, thumb=None, valid_grids=[])

        if not WSI_PROCESSING_AVAILABLE:
            raise RuntimeError(
                "rocqipath.registration.registrar is not installed. "
                "Install the package or set dry_run=True."
            )

        registrar = WSIRegistrar(
            case.reference_file,
            case.moving_file,
            self._make_registrar_cfg(Path(output_root), case.case_id),
            valis_cfg=self._make_valis_config(),
        )

        registrar.register_slides(method=self.cfg.alignment_method)
        thumb, valid_grids = registrar.generate_grid_map()
        aligned_path = registrar.save_aligned_wsi(
            level=self.cfg.aligned_wsi_level,
            output_path=str(Path(registrar.output_dir) / "aligned_moving.ome.tiff"),
        )

        return AlignedCaseResult(
            case=case,
            registrar=registrar,
            thumb=thumb,
            valid_grids=valid_grids,
            aligned_moving_path=aligned_path,
        )

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> List[AlignedCaseResult]:
        """
        Process every alignment pair folder and return alignment results.

        For each pair folder:
        1. Index the ``<reference_name>/`` and ``<moving_name>/`` subdirectories.
        2. Build reference/moving pairs by ``sample_id``.
        3. Register and save each pair (unless ``dry_run=True``).
        4. Optionally generate a centre-patch QC PNG per case.

        Returns
        -------
        List[AlignedCaseResult]
        """
        all_results: List[AlignedCaseResult] = []
        total_ok = total_fail = 0

        for pair_name in self.pair_folders:
            pair_path = self.input_dir / pair_name
            if not pair_path.is_dir():
                logger.warning(f"Alignment pair folder not found: {pair_path}")
                continue

            module_out = OutputLayout(self.output_dir).module_dir("alignment")
            logger.info(f"Pair folder: {pair_name}  →  {module_out}")

            index = index_pair_folder(
                pair_path,
                self._pattern,
                reference_name=self.cfg.reference_name,
                moving_name=self.cfg.moving_name,
            )
            pairs = build_sample_pairs(index)

            if not pairs:
                logger.warning(
                    f"No complete {self.cfg.reference_name}/{self.cfg.moving_name} "
                    f"pairs found in {pair_path}"
                )
                continue

            ok = fail = 0

            with tqdm(pairs, desc=f"Aligning {pair_name}", unit="pair") as pbar:
                for sample_id, reference_path, moving_path in pbar:
                    case_id = f"{sample_id}_{pair_name.lower()}"
                    pbar.set_description(f"{pair_name} | {sample_id}")

                    case = CaseContext(
                        case_id=case_id,
                        sample_id=sample_id,
                        pair_name=pair_name,
                        reference_file=reference_path,
                        moving_file=moving_path,
                    )

                    if self.cfg.dry_run:
                        logger.info(
                            f"[DRY RUN] {case_id}"
                            f"  {self.cfg.reference_name}={reference_path}"
                            f"  {self.cfg.moving_name}={moving_path}"
                        )
                        ok += 1
                        continue

                    registrar = None
                    try:
                        pbar.set_postfix(status="registering")
                        aligned = self.align_case(case, self.output_dir)
                        registrar = aligned.registrar
                        all_results.append(aligned)
                        ok += 1
                        logger.info(f"[OK] {case_id}")

                        # Optional QC
                        if self.cfg.qc_enabled and registrar is not None:
                            try:
                                pbar.set_postfix(status="qc")
                                qc_root = Path(
                                    self.cfg.qc_output_dir or str(Path(registrar.output_dir))
                                )
                                moving_qc = aligned.aligned_moving_path or case.moving_file
                                qc_center_patch_side_by_side(
                                    reference_path=case.reference_file,
                                    moving_path=str(moving_qc),
                                    out_png=str(qc_root / f"{case_id}_center_qc.png"),
                                    reference_level=self.cfg.qc_reference_level,
                                    patch_size=self.cfg.qc_patch_size,
                                    reference_read_level=self.cfg.qc_reference_read_level,
                                    moving_read_level=self.cfg.qc_moving_read_level,
                                    title=case_id,
                                    dpi=self.cfg.qc_dpi,
                                )
                            except Exception as qc_err:
                                logger.warning(f"[QC WARN] {case_id}: {qc_err}")

                    except Exception as exc:
                        # The previous handler logged only str(exc), leaving a
                        # single sentence to diagnose a failed case from.
                        # format_exc() works with stdlib logging and loguru
                        # alike, unlike logger.exception().
                        logger.error(f"[FAIL] {case_id}: {exc}\n{traceback.format_exc()}")
                        fail += 1
                    finally:
                        if registrar is not None:
                            try:
                                registrar.close()
                            except Exception:
                                pass
                        pbar.set_postfix(status="done")

            total_ok += ok
            total_fail += fail
            logger.info(f"{pair_name} — ok={ok}  failed={fail}")

        logger.info(f"Alignment complete — total ok={total_ok}  failed={total_fail}")
        return all_results


def run_alignment(config: AlignmentConfig) -> List[AlignedCaseResult]:
    """
    Run the full alignment pipeline from a typed ``AlignmentConfig``.

    This is the **primary entry point** for programmatic use:

        from rocqipath.registration import run_alignment, AlignmentConfig

        results = run_alignment(AlignmentConfig(
            input_dir  = "./data/wsi",
            output_dir = "./data/wsi/aligned",
        ))

    Parameters
    ----------
    config : AlignmentConfig

    Returns
    -------
    List[AlignedCaseResult]
    """
    from rocqipath.core.console import print_banner

    print_banner()
    return AlignmentProcessor(config).run()
