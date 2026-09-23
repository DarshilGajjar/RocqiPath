"""Adapter between the golden tests and the RocqiPath API.

This is the only golden-test file that later restructuring phases edit when
an import path or call signature changes. Each call builds its synthetic
input under ``root``, runs one workflow and returns ``(output_dir, returned)``
where ``returned`` holds the workflow's own return values in plain JSON form.
The expected snapshots in ``expected/`` must not change when this file does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Tuple

import numpy as np

from tests.golden import _data as D

Call = Callable[[Path], Tuple[Path, dict]]

#: Optional modules each call needs; the test is skipped when one is missing.
REQUIRES: Dict[str, Tuple[str, ...]] = {
    "extract_tissue": ("pyvips", "cv2"),
    "extract_tma": ("pyvips", "cv2"),
    "extract_patches": ("cv2", "openslide"),
    "reversible_patches": ("cv2", "pyvips"),
    "align_orb": ("pyvips", "openslide", "cv2"),
    "stain_reinhard": ("tiatoolbox",),
    "stain_macenko": ("tiatoolbox",),
    "count_single": ("cv2", "skimage"),
    "count_batch": ("cv2", "skimage"),
    "count_pair": ("cv2", "skimage", "matplotlib", "openpyxl"),
    "overlay_markers": ("cv2", "matplotlib"),
    "compare": ("cv2", "matplotlib"),
    "grid_map": ("matplotlib",),
}


def extract_tissue(root: Path) -> Tuple[Path, dict]:
    from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

    out = root / "out"
    results = run_tissue_pipeline(
        str(D.make_tissue_slides(root)),
        str(out),
        TissueExtractionConfig(source_magnification=D.SOURCE_MAG, target_magnification=5.0),
    )
    return out, {"regions": results}


def extract_tma(root: Path) -> Tuple[Path, dict]:
    from rocqipath.extraction import TMAExtractionConfig, run_tma_extraction_pipeline

    out = root / "out"
    run_tma_extraction_pipeline(
        str(D.make_tma(root)),
        str(out),
        TMAExtractionConfig(source_magnification=D.SOURCE_MAG, target_magnification=5.0),
    )
    return out, {}


def extract_patches(root: Path) -> Tuple[Path, dict]:
    from rocqipath.extraction import PatchExtractionConfig, run_patch_extraction

    data = D.make_patch_pairs(root)
    out = root / "out"
    summary = run_patch_extraction(
        PatchExtractionConfig(
            he_dir=str(data["reference_root"]),
            aligned_dir=str(data["aligned_root"]),
            output_dir=str(out),
            biomarker_folders=["CD8"],
            reference_pattern=r"^(?P<sample_id>Sample_\d{4})_he\.tiff?$",
            moving_name="cd8",
            patch_size=64,
            stride=64,
            tissue_threshold=0.5,
            reference_source_magnification=D.SOURCE_MAG,
            target_source_magnification=D.SOURCE_MAG,
        )
    )
    return out, {"summary": summary}


def reversible_patches(root: Path) -> Tuple[Path, dict]:
    from rocqipath.extraction import ReversiblePatchExtractor

    data = D.make_reversible(root)
    out = root / "out"
    extractor = ReversiblePatchExtractor(
        {
            "he_root": str(data["he_root"]),
            "aligned_root": str(data["aligned_root"]),
            "biomarker_folders": ["CD8"],
            "output_dir": str(out),
            "patch_size": 64,
            "stride": 64,
            "tissue_threshold": 0.5,
            "reference_source_magnification": D.SOURCE_MAG,
            "target_source_magnification": D.SOURCE_MAG,
        }
    )
    extractor.run()
    rebuilt = {
        mode: extractor.reconstruct_wsi("Sample_0001_CD8", "CD8", str(out), mode=mode)
        for mode in ("he", "ihc")
    }
    return out, {"reconstruct": rebuilt}


def align_orb(root: Path) -> Tuple[Path, dict]:
    from rocqipath.alignment import AlignmentConfig, run_alignment

    out = root / "out"
    results = run_alignment(
        AlignmentConfig(
            input_dir=str(D.make_alignment_pair(root)),
            output_dir=str(out),
            pair_folders=["CD8"],
            reference_name="he",
            moving_name="cd8",
            alignment_method="orb",
            reference_source_magnification=D.SOURCE_MAG,
            moving_source_magnification=D.SOURCE_MAG,
            target_magnification=D.SOURCE_MAG,
            qc_enabled=True,
        )
    )
    returned = [
        {
            "case_id": r.case.case_id,
            "sample_id": r.case.sample_id,
            "pair_name": r.case.pair_name,
            "valid_grids": list(r.valid_grids),
            "aligned": Path(r.aligned_moving_path).name,
            "residual_shift_px": _residual_shift(r.case.reference_file, r.aligned_moving_path),
        }
        for r in results
    ]
    for r in results:
        r.registrar.close()
    return out, {"cases": returned}


def _residual_shift(reference: str, aligned: str) -> list:
    """Whole-pixel translation left between the reference and aligned slides."""
    import cv2
    from PIL import Image

    ref = np.asarray(Image.open(reference).convert("L"), dtype=np.float32)
    mov = np.asarray(Image.open(aligned).convert("L"), dtype=np.float32)
    h, w = min(ref.shape[0], mov.shape[0]), min(ref.shape[1], mov.shape[1])
    (dx, dy), _ = cv2.phaseCorrelate(ref[:h, :w], mov[:h, :w])
    return [int(round(dx)), int(round(dy))]


def _stain(root: Path, method: str) -> Tuple[Path, dict]:
    from rocqipath.stain import (
        StainNormalizationConfig,
        run_stain_normalization_apply,
        run_stain_normalization_train,
    )

    src = D.make_stain_patches(root)
    out = root / "out"
    cfg = StainNormalizationConfig(n_type=method, stains=["he"])
    weights = run_stain_normalization_train(str(src), str(out), cfg)
    applied = run_stain_normalization_apply(str(src), str(out), cfg)
    return out, {"weights": Path(weights).name, "applied": applied}


def stain_reinhard(root: Path) -> Tuple[Path, dict]:
    return _stain(root, "reinhard")


def stain_macenko(root: Path) -> Tuple[Path, dict]:
    return _stain(root, "macenko")


def _counter(root: Path):
    from rocqipath.counting import CellCountingConfig, PositiveCellCounter

    return PositiveCellCounter(
        CellCountingConfig(
            output_dir=str(root / "out"),
            source_magnification=D.SOURCE_MAG,
            paired_source_magnification=D.SOURCE_MAG,
            target_magnification=D.SOURCE_MAG,
            patch_size=256,
            min_cell_area=20,
        )
    )


def count_single(root: Path) -> Tuple[Path, dict]:
    slides = D.make_count_slides(root)
    return root / "out", {"result": _counter(root).count_slide(str(slides["gt"]), label="CD8")}


def count_batch(root: Path) -> Tuple[Path, dict]:
    slides = D.make_count_slides(root)
    return root / "out", {"results": _counter(root).count_batch(str(slides["dir"]), label="CD8")}


def count_pair(root: Path) -> Tuple[Path, dict]:
    slides = D.make_count_slides(root)
    result = _counter(root).count_slide_pair(
        str(slides["gt"]), str(slides["pred"]), label="CD8", dpi=50, max_plots=2
    )
    return root / "out", {"result": result}


def overlay_markers(root: Path) -> Tuple[Path, dict]:
    from rocqipath.viz import (
        IHCOverlayConfig,
        MarkerProfile,
        OverlayCombo,
        process_ihc_overlay,
    )

    out = root / "out"
    cfg = IHCOverlayConfig(
        markers={"he": MarkerProfile(color=(0, 0, 255)), "cd8": MarkerProfile(color=(255, 0, 0))},
        combinations=[OverlayCombo(base="he", overlays=["cd8"])],
        base_marker="he",
        save_dir=str(out),
        dpi=50,
    )
    return out, {"result": process_ihc_overlay(str(D.make_overlay_case(root)), cfg)}


def compare(root: Path) -> Tuple[Path, dict]:
    from rocqipath.viz.comparison import visualize_side_by_side

    slides = D.make_compare_slides(root)
    out = root / "out"
    out.mkdir(parents=True)
    visualize_side_by_side(
        str(slides["he"]),
        str(slides["gt"]),
        str(slides["pred"]),
        str(out / "comparison.png"),
        dpi=50,
        title_he="HE",
        title_gt="GT",
        title_pred="Pred",
        regions=["center"],
        zoom_sizes=[("detail", 256)],
        n_random_rois=1,
        add_scale_bars=True,
        mpp=0.5,
    )
    return out, {}


def grid_map(root: Path) -> Tuple[Path, dict]:
    from PIL import Image

    from rocqipath.viz import plot_selector_map

    out = root / "out"
    out.mkdir(parents=True)
    thumb = Image.open(D.make_tissue_slides(root) / "slideA.tif")
    plot_selector_map(thumb, {0, 3, 5}, 3, 4, str(out / "grid.png"), show=False)
    return out, {}


CALLS: Dict[str, Call] = {
    name: globals()[name] for name in REQUIRES
}
