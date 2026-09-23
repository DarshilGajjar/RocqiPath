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
    import rocqipath as rp

    result = rp.extract_tissue(
        D.make_tissue_slides(root),
        root / "out",
        source_magnification=D.SOURCE_MAG,
        target_magnification=5.0,
    )
    return result.output_dir, {"regions": result.summary["regions"]}


def extract_tma(root: Path) -> Tuple[Path, dict]:
    import rocqipath as rp

    result = rp.extract_tma(
        D.make_tma(root), root / "out", source_magnification=D.SOURCE_MAG, target_magnification=5.0
    )
    return result.output_dir, {}


def extract_patches(root: Path) -> Tuple[Path, dict]:
    import rocqipath as rp

    data = D.make_patch_pairs(root)
    result = rp.extract_patches(
        data["aligned_root"],
        root / "out",
        reference=data["reference_root"],
        biomarker_folders=["CD8"],
        reference_pattern=r"^(?P<sample_id>Sample_\d{4})_he\.tiff?$",
        moving_name="cd8",
        patch_size=64,
        stride=64,
        tissue_threshold=0.5,
        reference_source_magnification=D.SOURCE_MAG,
        target_source_magnification=D.SOURCE_MAG,
    )
    return result.output_dir, {"summary": result.summary}


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
    import rocqipath as rp

    result = rp.align(
        D.make_alignment_pair(root),
        root / "out",
        pair_folders=["CD8"],
        reference_name="he",
        moving_name="cd8",
        backend="orb",
        reference_source_magnification=D.SOURCE_MAG,
        moving_source_magnification=D.SOURCE_MAG,
        target_magnification=D.SOURCE_MAG,
        qc_enabled=True,
    )
    references = {item.meta["case_id"]: item for item in result.by_role("reference")}
    returned = [
        {
            "case_id": item.meta["case_id"],
            "sample_id": item.sample_id,
            "pair_name": item.meta["pair"],
            "valid_grids": item.meta["valid_grids"],
            "aligned": item.path.name,
            "residual_shift_px": _residual_shift(
                str(references[item.meta["case_id"]].path), str(item.path)
            ),
        }
        for item in result.by_role("aligned")
    ]
    return result.output_dir, {"cases": returned}


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
    import rocqipath as rp

    src = D.make_stain_patches(root)
    weights = rp.train_stain_normalizer(src, root / "out", method=method, stains=["he"])
    applied = rp.normalize_stain(src, root / "out", normalizer=weights, stains=["he"])
    return applied.output_dir, {
        "weights": weights.by_role("weights")[0].path.name,
        "applied": applied.summary,
    }


def stain_reinhard(root: Path) -> Tuple[Path, dict]:
    return _stain(root, "reinhard")


def stain_macenko(root: Path) -> Tuple[Path, dict]:
    return _stain(root, "macenko")


_COUNT_SETTINGS = dict(
    label="CD8",
    source_magnification=D.SOURCE_MAG,
    paired_source_magnification=D.SOURCE_MAG,
    target_magnification=D.SOURCE_MAG,
    patch_size=256,
    min_cell_area=20,
)


def count_single(root: Path) -> Tuple[Path, dict]:
    import rocqipath as rp

    slides = D.make_count_slides(root)
    result = rp.count_cells(slides["gt"], root / "out", **_COUNT_SETTINGS)
    return result.output_dir, {"result": result.summary["results"][0]}


def count_batch(root: Path) -> Tuple[Path, dict]:
    import rocqipath as rp

    slides = D.make_count_slides(root)
    result = rp.count_cells(slides["dir"], root / "out", **_COUNT_SETTINGS)
    return result.output_dir, {"results": result.summary["results"]}


def count_pair(root: Path) -> Tuple[Path, dict]:
    import rocqipath as rp

    slides = D.make_count_slides(root)
    result = rp.count_cells(
        slides["gt"], root / "out", compare_to=slides["pred"], dpi=50, max_plots=2, **_COUNT_SETTINGS
    )
    return result.output_dir, {"result": result.summary["result"]}


def overlay_markers(root: Path) -> Tuple[Path, dict]:
    import rocqipath as rp

    result = rp.overlay_markers(
        D.make_overlay_case(root),
        root / "out",
        markers={"he": rp.MarkerProfile(color=(0, 0, 255)), "cd8": rp.MarkerProfile(color=(255, 0, 0))},
        combinations=[rp.OverlayCombo(base="he", overlays=["cd8"])],
        base_marker="he",
        dpi=50,
    )
    return result.output_dir, {"result": result.summary}


def compare(root: Path) -> Tuple[Path, dict]:
    import rocqipath as rp

    slides = D.make_compare_slides(root)
    result = rp.compare(
        [slides["he"], slides["gt"], slides["pred"]],
        root / "out",
        dpi=50,
        title_reference="HE",
        title_truth="GT",
        title_prediction="Pred",
        regions=["center"],
        zooms=["detail:256"],
        random_rois=1,
        scale_bars=True,
        mpp=0.5,
    )
    return result.output_dir, {}


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
