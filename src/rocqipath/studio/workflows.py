"""Explicit adapters from Studio selections to the existing library APIs."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

WORKFLOWS = {
    "extract": {"label": "Tissue extraction", "modules": ["numpy", "cv2", "PIL", "pyvips", "tqdm"], "extra": "extraction", "inputs": 1},
    "align": {"label": "Slide alignment", "modules": ["numpy", "cv2", "PIL", "openslide", "pyvips", "tqdm"], "extra": "orb", "inputs": 2},
    "stain": {"label": "Stain normalization", "modules": ["numpy", "cv2", "PIL", "tiatoolbox"], "extra": "stain", "inputs": 2},
    "count": {"label": "Cell counting", "modules": ["numpy", "cv2", "PIL", "skimage", "matplotlib", "openpyxl", "tqdm"], "extra": "cellcount", "inputs": 1},
    "compare": {"label": "Comparison figure", "modules": ["numpy", "cv2", "PIL", "matplotlib", "openslide"], "extra": "viz", "inputs": 3},
}


def capabilities():
    """Report package availability, including native library load failures."""
    installed = {}
    for module in {m for config in WORKFLOWS.values() for m in config["modules"]} | {"valis", "zarr"}:
        try:
            if importlib.util.find_spec(module) is None:
                raise ImportError(module)
            if module in {"pyvips", "openslide"}:
                importlib.import_module(module)
            installed[module] = True
        except Exception:
            installed[module] = False
    return {name: {**config, "available": all(installed[m] for m in config["modules"]),
        "missing": [m for m in config["modules"] if not installed[m]],
        "valis": installed["valis"], "semantic": installed["tiatoolbox"] and installed["zarr"] and installed["openslide"]}
        for name, config in WORKFLOWS.items()}


def execute(workflow, inputs, p, output):
    """Run real library calls and let processing failures reach the worker."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = p.get("source_magnification")
    target = p.get("target_magnification", 20)
    print(f"Starting {WORKFLOWS[workflow]['label']}", flush=True)
    for path in inputs:
        print(f"Input: {path}", flush=True)
    if workflow == "count":
        from rocqipath.analysis import PositiveCellCounter
        from rocqipath.config import CellCountingConfig
        counter = PositiveCellCounter(CellCountingConfig(
            output_dir=str(output), source_magnification=source, target_magnification=target,
            patch_size=p.get("patch_size", 512), min_cell_area=p.get("min_cell_area", 50),
            tissue_threshold=p.get("tissue_threshold", 0.1)))
        result = counter.count_slide(inputs[0], label="DAB-positive")
    elif workflow == "extract":
        from rocqipath.config import TissueExtractionConfig
        from rocqipath.extraction.tissue import extract_tissue_regions
        result = extract_tissue_regions(inputs[0], str(output), TissueExtractionConfig(
            source_magnification=source, target_magnification=target,
            detection_magnification=p.get("detection_magnification", 1.25),
            min_area_fraction=p.get("min_area_fraction", 0.005),
            detector=p.get("detector", "otsu")))
        print(f"Detected {len(result)} tissue regions.", flush=True)
    elif workflow == "align":
        from rocqipath.registration import WSIRegistrar
        from rocqipath.registration.pipeline import _write_aligned_wsi_manifest
        registrar = WSIRegistrar(inputs[0], inputs[1], {
            "base_output_dir": str(output), "patch_size": 512, "grid_density": 10,
            "target_magnification": target, "reference_source_magnification": source,
            "moving_source_magnification": p.get("moving_source_magnification"),
        })
        try:
            registrar.register_slides(method=p.get("method", "orb"))
            if not registrar.registration_ok:
                raise RuntimeError("Alignment failed the registration quality checks. See the log.")
            saved = registrar.save_aligned_wsi(level=0, output_path=str(output / "aligned.ome.tiff"))
            if not saved or not Path(saved).is_file() or not Path(saved).stat().st_size:
                raise RuntimeError("Aligned slide export did not produce a file.")
            _write_aligned_wsi_manifest(aligned_path=saved, reference_path=inputs[0],
                alignment_target_magnification=target, aligned_wsi_level=0,
                reference_source_magnification=source)
            result = {"aligned_slide": saved}
        finally:
            registrar.close()
    elif workflow == "stain":
        from PIL import Image
        from rocqipath.stain import get_normalizer
        from rocqipath.utils.imageio import imread_rgb, imwrite_rgb
        for path in inputs:
            with Image.open(path) as image:
                if image.width * image.height > 25_000_000:
                    raise ValueError("Normalize extracted patches or images under 25 megapixels, not full slides.")
        normalizer = get_normalizer(p.get("algorithm", "reinhard"))
        reference, image = imread_rgb(Path(inputs[1])), imread_rgb(Path(inputs[0]))
        if reference is None or image is None:
            raise ValueError("Could not read the source or reference image.")
        normalizer.fit(reference)
        normalizer.save_weights(output / "weights.npz")
        imwrite_rgb(output / "normalized.png", normalizer.transform(image))
        result = {"image": "normalized.png", "weights": "weights.npz"}
    elif workflow == "compare":
        from rocqipath.visualization.comparison_workflow import visualize_side_by_side
        visualize_side_by_side(inputs[0], inputs[1], inputs[2], str(output / "comparison.png"),
            dpi=p.get("dpi", 150), title_he="Reference", title_gt="Comparison A", title_pred="Comparison B",
            regions=["center"], zoom_sizes=[("detail", 512)], n_random_rois=0, add_scale_bars=False)
        result = {"figure": "comparison.png"}
    else:
        raise ValueError("Unknown workflow")
    (output / "summary.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("Processing completed. Results saved.", flush=True)
    return result
