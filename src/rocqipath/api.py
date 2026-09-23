"""Every workflow RocqiPath can run, in one place.

Each function here follows the same pattern::

    result = rp.<workflow>(inputs, output_dir, *, config=None, **settings)

``inputs`` names what to process (files or folders), ``output_dir`` is where
results go, and ``settings`` are fields of the workflow's config class, given
either as keywords or as a complete ``config=`` object. The return value is a
:class:`~rocqipath.registry.Result` listing every file produced.

Heavy dependencies (OpenCV, libvips, OpenSlide, TIAToolbox, VALIS) are
imported inside the functions, so importing this module is cheap and
:func:`rocqipath.list_workflows` works without any extras installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from rocqipath.alignment.config import AlignConfig
from rocqipath.counting.config import CountCellsConfig
from rocqipath.extraction.config import ExtractPatchesConfig, ExtractTissueConfig, ExtractTMAConfig
from rocqipath.registry import InputSpec, Item, Result, workflow
from rocqipath.stain.config import StainConfig
from rocqipath.viz.config import CompareConfig, OverlayConfig

PathLike = Union[str, Path]
Outputs = Tuple[List[Item], Dict[str, Any]]

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def _one_folder(inputs: Sequence[Path], workflow_name: str) -> Path:
    """Return the single input folder a folder-based workflow expects."""
    if len(inputs) != 1 or not inputs[0].is_dir():
        raise ValueError(f"{workflow_name} expects one input folder; got {[str(p) for p in inputs]}")
    return inputs[0]


def _files(folder: Path, suffixes: Iterable[str] = _IMAGE_SUFFIXES) -> List[Path]:
    """Every file under ``folder`` with one of ``suffixes``, in a stable order."""
    wanted = {suffix.lower() for suffix in suffixes}
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in wanted)


# ── Extraction ──────────────────────────────────────────────────────────────


@workflow(
    "extract_tissue",
    config=ExtractTissueConfig,
    extra="extraction",
    inputs=InputSpec(kind="whole-slide images or folders of them", roles=("slide", "aligned")),
)
def extract_tissue(inputs: List[Path], output_dir: Path, *, config: ExtractTissueConfig) -> Outputs:
    """Cut each separate piece of tissue out of whole-slide images.

    Tissue is detected on a low-magnification thumbnail (Otsu thresholding
    by default, or a TIAToolbox model with ``detector="semantic"``). Each
    region is saved at ``target_magnification`` as a pyramidal TIFF with a
    JPEG preview and a JSON manifest recording its position on the slide.

    Parameters
    ----------
    inputs : path, list of paths or Result
        Slide files and/or folders of slides (``.svs``, ``.ndpi``,
        ``.tif``, ...). Folders are not searched recursively.
    output_dir : path
        Results go to ``<output_dir>/tissue_extraction/<slide>/``.
    config : ExtractTissueConfig, optional
        Complete settings. Individual fields may instead be given as
        keywords, e.g. ``target_magnification=10``.

    Returns
    -------
    Result
        One ``"region"`` item per saved or already-existing region, with its
        box in ``meta``. ``summary["regions"]`` maps each slide name to its
        region records.

    Examples
    --------
    >>> import rocqipath as rp
    >>> result = rp.extract_tissue("slides/", "results/", target_magnification=10)  # doctest: +SKIP
    >>> [item.path.name for item in result.by_role("region")]  # doctest: +SKIP
    ['region_001.tif', 'region_002.tif']
    """
    from rocqipath.extraction.regions import run_tissue_pipeline

    regions = run_tissue_pipeline([str(p) for p in inputs], str(output_dir), config)
    sources = {p.stem: p for p in _expand_slides(inputs)}
    items = []
    for slide, records in regions.items():
        for record in records:
            items.append(
                Item(
                    sample_id=slide,
                    role="region",
                    path=output_dir / "tissue_extraction" / slide / f"{record['region_tag']}.tif",
                    magnification=config.target_magnification,
                    source=sources.get(slide),
                    meta={k: v for k, v in record.items() if k != "region_tag"},
                )
            )
    return items, {"regions": regions}


def _expand_slides(inputs: Sequence[Path]) -> List[Path]:
    """Slide files named directly or found directly inside folders."""
    from rocqipath.io.discovery import is_wsi_file

    slides: List[Path] = []
    for path in inputs:
        if path.is_dir():
            slides.extend(sorted(p for p in path.iterdir() if p.is_file() and is_wsi_file(p.name)))
        else:
            slides.append(path)
    return slides


@workflow(
    "extract_tma",
    config=ExtractTMAConfig,
    extra="extraction",
    inputs=InputSpec(kind="a folder of H&E and IHC TMA slides"),
)
def extract_tma(inputs: List[Path], output_dir: Path, *, config: ExtractTMAConfig) -> Outputs:
    """Cut tissue-microarray cores out of H&E slides and their matching IHC slides.

    Slides are grouped into blocks by the sample ID in their filenames and
    classified as H&E or a marker by keyword (``HE``, ``CD8``, ...). Cores
    are detected on the H&E slide and the same boxes are cut from each IHC
    slide of the block (or detected per stain with
    ``per_stain_detection=True``).

    Parameters
    ----------
    inputs : path
        Folder searched recursively for TMA slides.
    output_dir : path
        Cores go to ``<output_dir>/tissue_extraction/<slide>/core_NNN.tif``.
    config : ExtractTMAConfig, optional
        Complete settings, or give fields as keywords (``stains=["HE", "CD8"]``).

    Returns
    -------
    Result
        One ``"core"`` item per saved core. ``summary["slides"]`` maps each
        slide folder to its number of cores.

    Examples
    --------
    >>> import rocqipath as rp
    >>> rp.extract_tma("tma_slides/", "results/", source_magnification=40)  # doctest: +SKIP
    """
    from rocqipath.extraction.tma import run_tma_extraction_pipeline

    for folder in inputs:
        run_tma_extraction_pipeline(str(folder), str(output_dir), config)
    items: List[Item] = []
    slides: Dict[str, int] = {}
    root = output_dir / "tissue_extraction"
    for manifest_path in sorted(root.glob("*/*_manifest.json")):
        if manifest_path.name.startswith("core_"):
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        folder = manifest_path.parent
        count = 0
        for region in manifest.get("regions", []):
            tag = region.get("core_tag") or f"core_{int(region.get('core_number', 0)):03d}"
            core = folder / f"{tag}.tif"
            if not core.exists():
                continue
            count += 1
            items.append(
                Item(
                    sample_id=manifest.get("sample_id", folder.name),
                    role="core",
                    path=core,
                    magnification=config.target_magnification,
                    meta={"slide": folder.name, "source_file": manifest.get("source_file"), **region},
                )
            )
        slides[folder.name] = count
    return items, {"slides": slides}


@workflow(
    "extract_patches",
    config=ExtractPatchesConfig,
    extra="extraction",
    inputs=InputSpec(kind="a folder of aligned slides from rp.align", roles=("aligned",)),
)
def extract_patches(
    inputs: List[Path],
    output_dir: Path,
    *,
    config: ExtractPatchesConfig,
    reference: Optional[PathLike] = None,
) -> Outputs:
    """Save matching patch pairs from reference slides and their aligned counterparts.

    A sliding window walks each reference slide at ``target_magnification``;
    wherever the reference patch holds at least ``tissue_threshold`` tissue,
    the same window is saved from the aligned slide as well, giving
    pixel-matched training or analysis pairs. A metadata JSON per case
    records every patch position so slides can be rebuilt later.

    Parameters
    ----------
    inputs : path or Result
        Folder of aligned slides laid out as
        ``<biomarker>/<sample>_<reference_name>/*.ome.tiff``.
    output_dir : path
        Pairs go to ``<output_dir>/patch_extraction/<sample>_<biomarker>/``.
    reference : path
        Folder searched recursively for reference slides whose names
        match ``reference_pattern``.
    config : ExtractPatchesConfig, optional
        Complete settings, or give fields as keywords (``patch_size=256``).

    Returns
    -------
    Result
        One ``"patch"`` item per saved patch image; ``meta`` holds its
        ``stain``, ``patch_id``, ``case_id`` and ``coordinates``.
        ``summary`` has ``processed``, ``skipped`` and per-case ``cases``.

    Examples
    --------
    >>> import rocqipath as rp
    >>> pairs = rp.extract_patches("aligned/", "results/", reference="he_slides/", patch_size=512)  # doctest: +SKIP
    """
    from rocqipath.extraction.patches import run_patch_extraction

    if reference is None:
        raise TypeError("extract_patches() needs reference= (the folder of reference slides)")
    aligned = _one_folder(inputs, "extract_patches")
    summary = run_patch_extraction(str(reference), str(aligned), str(output_dir), config)
    items: List[Item] = []
    for case in summary["cases"]:
        if case.get("status") != "processed":
            continue
        case_dir = output_dir / "patch_extraction" / case["case_id"]
        metadata = json.loads(
            (case_dir / f"{case['case_id']}_metadata.json").read_text(encoding="utf-8")
        )
        sample_id = case["case_id"].rsplit("_", 1)[0]
        for patch in metadata.get("patches", []):
            for key, value in sorted(patch.items()):
                if key.endswith("_path"):
                    items.append(
                        Item(
                            sample_id=sample_id,
                            role="patch",
                            path=Path(value),
                            magnification=config.target_magnification,
                            meta={
                                "stain": key[: -len("_path")],
                                "patch_id": patch.get("id"),
                                "case_id": case["case_id"],
                                "coordinates": patch.get("coordinates"),
                            },
                        )
                    )
    return items, summary


# ── Alignment ───────────────────────────────────────────────────────────────


@workflow(
    "align",
    config=AlignConfig,
    extra="orb",
    inputs=InputSpec(kind="a folder of pair folders, or two slides: reference then moving"),
)
def align(inputs: List[Path], output_dir: Path, *, config: AlignConfig) -> Outputs:
    """Register moving slides (e.g. IHC) onto reference slides (e.g. H&E).

    Pairs are discovered in pair folders such as ``cd8/he/`` and ``cd8/cd8/``
    and matched by the sample ID in their filenames. Each moving slide is
    registered with VALIS (rigid plus non-rigid, the default) or the
    lightweight ORB backend (``backend="orb"``) and exported as a pyramidal
    OME-TIFF in the reference slide's coordinates, with a manifest recording
    its magnification. Optional QC figures show the aligned centers.

    Parameters
    ----------
    inputs : path or [reference, moving]
        Folder containing the pair folders, or two slide files to align
        directly (reference first).
    output_dir : path
        Aligned slides go to ``<output_dir>/alignment/<sample>_<moving>/``.
    config : AlignConfig, optional
        Complete settings, or give fields as keywords. Backend settings
        are nested: ``valis__max_acceptable_error_um=100`` or
        ``orb__ransac_threshold=10``.

    Returns
    -------
    Result
        For every registered pair, an ``"aligned"`` item (the exported
        slide) and a ``"reference"`` item (the untouched reference slide it
        matches), plus ``"figure"`` items for QC images.
        ``summary["cases"]`` lists each pair.

    Examples
    --------
    >>> import rocqipath as rp
    >>> result = rp.align("pairs/", "results/", backend="orb", reference_name="he", moving_name="cd8")  # doctest: +SKIP
    >>> result.by_role("aligned")[0].path.name  # doctest: +SKIP
    'case01_cd8_aligned_moving.ome.tiff'
    """
    from rocqipath.alignment.pipeline import align_pair, run_alignment

    if len(inputs) == 2 and all(path.is_file() for path in inputs):
        results = [align_pair(inputs[0], inputs[1], output_dir, config)]
    else:
        results = run_alignment(str(_one_folder(inputs, "align")), str(output_dir), config)
    items: List[Item] = []
    cases = []
    try:
        for aligned in results:
            case = aligned.case
            if not aligned.aligned_moving_path:
                continue
            common = {"pair": case.pair_name, "case_id": case.case_id}
            items.append(
                Item(
                    sample_id=case.sample_id,
                    role="reference",
                    path=Path(case.reference_file),
                    meta=common,
                )
            )
            items.append(
                Item(
                    sample_id=case.sample_id,
                    role="aligned",
                    path=Path(aligned.aligned_moving_path),
                    magnification=config.target_magnification,
                    source=Path(case.moving_file),
                    meta={**common, "valid_grids": list(aligned.valid_grids)},
                )
            )
            case_dir = Path(aligned.aligned_moving_path).parent
            for figure in sorted(case_dir.glob("*.png")):
                items.append(Item(sample_id=case.sample_id, role="figure", path=figure, meta=common))
            cases.append(
                {
                    **common,
                    "sample_id": case.sample_id,
                    "aligned": str(aligned.aligned_moving_path),
                    "reference": str(case.reference_file),
                }
            )
    finally:
        for aligned in results:
            if aligned.registrar is not None:
                aligned.registrar.close()
    return items, {"cases": cases}


# ── Stain normalization ─────────────────────────────────────────────────────


@workflow(
    "train_stain_normalizer",
    config=StainConfig,
    extra="stain",
    inputs=InputSpec(kind="a folder of reference patches", roles=("patch", "normalized")),
)
def train_stain_normalizer(inputs: List[Path], output_dir: Path, *, config: StainConfig) -> Outputs:
    """Fit a stain normalizer to reference patches and save its weights.

    Patches under the input folder whose path contains one of ``stains``
    and that hold enough tissue are sampled; Reinhard fits color
    statistics incrementally, while Macenko and Vahadane fit stain vectors
    on a mosaic of up to ``max_train_patches`` patches.

    Parameters
    ----------
    inputs : path or list of paths
        Reference image patches, or folders searched recursively for them.
    output_dir : path
        Weights go to ``<output_dir>/stain_normalization/<method>_weights.npz``.
    config : StainConfig, optional
        Complete settings, or give fields as keywords (``method="reinhard"``).

    Returns
    -------
    Result
        One ``"weights"`` item. Pass the result as ``normalizer=`` to
        :func:`normalize_stain`.

    Examples
    --------
    >>> import rocqipath as rp
    >>> weights = rp.train_stain_normalizer("reference_patches/", "results/", method="macenko")  # doctest: +SKIP
    >>> rp.normalize_stain("patches/", "results/", normalizer=weights)  # doctest: +SKIP
    """
    from rocqipath.stain.batch import run_stain_normalization_train

    weights = Path(run_stain_normalization_train(inputs, str(output_dir), config))
    item = Item(sample_id=config.method, role="weights", path=weights, meta={"method": config.method})
    return [item], {"weights": str(weights), "method": config.method}


@workflow(
    "normalize_stain",
    config=StainConfig,
    extra="stain",
    inputs=InputSpec(kind="a folder of image patches", roles=("patch", "region", "core")),
)
def normalize_stain(
    inputs: List[Path],
    output_dir: Path,
    *,
    config: StainConfig,
    normalizer: Union[PathLike, Result, None] = None,
) -> Outputs:
    """Recolor image patches so their stain matches a trained normalizer.

    Parameters
    ----------
    inputs : path or list of paths
        Images to normalize, or folders searched recursively for images
        whose path contains one of ``stains``.
    output_dir : path
        Normalized images go to ``<output_dir>/stain_normalization/<name>/``,
        where ``<name>`` joins the patch's relative path with ``__``.
    normalizer : path or Result
        Saved weights (``.npz``) or the result of
        :func:`train_stain_normalizer`. The method is taken from the
        training result, or from a ``<method>_weights.npz`` filename, and
        otherwise from ``method``.
    config : StainConfig, optional
        Complete settings, or give fields as keywords (``resume=True``).

    Returns
    -------
    Result
        One ``"normalized"`` item per written image. ``summary`` has
        ``processed``, ``skipped``, ``failed`` and ``total`` counts.

    Examples
    --------
    >>> import rocqipath as rp
    >>> rp.normalize_stain("patches/", "results/", normalizer="weights/macenko_weights.npz")  # doctest: +SKIP
    """
    from rocqipath.stain.batch import run_stain_normalization_apply
    from rocqipath.stain.config import NORMALIZER_TYPES

    if normalizer is None:
        raise TypeError("normalize_stain() needs normalizer= (weights file or training result)")
    if isinstance(normalizer, Result):
        weights = normalizer.by_role("weights")[0].path
        config = config.replace(method=normalizer.config.method)
    else:
        weights = Path(normalizer)
        prefix = weights.name.split("_weights", 1)[0].lower()
        if weights.name.lower().endswith("_weights.npz") and prefix in NORMALIZER_TYPES:
            config = config.replace(method=prefix)
    summary = run_stain_normalization_apply(inputs, str(output_dir), config, weights)
    root = output_dir / "stain_normalization"
    items = [
        Item(sample_id=path.parent.name, role="normalized", path=path)
        for path in _files(root)
        if path.parent != root
    ]
    return items, summary


# ── Analysis ────────────────────────────────────────────────────────────────


@workflow(
    "count_cells",
    config=CountCellsConfig,
    extra="cellcount",
    inputs=InputSpec(kind="IHC slides or a folder of them", roles=("aligned", "slide")),
)
def count_cells(
    inputs: List[Path],
    output_dir: Path,
    *,
    config: CountCellsConfig,
    compare_to: Optional[PathLike] = None,
) -> Outputs:
    """Count DAB-positive (brown) cells on IHC slides.

    Each slide is read at ``target_magnification`` in ``patch_size`` tiles;
    tiles with enough tissue are counted independently and the counts,
    tissue area and density are summed per slide. With ``compare_to``, two
    slides (e.g. real and predicted IHC) are counted on the same grid and
    compared, with per-patch figures and an Excel sheet.

    Parameters
    ----------
    inputs : path, list of paths or Result
        One slide, several slides, or a folder of slides.
    output_dir : path
        Results go to ``<output_dir>/cell_counting/``.
    compare_to : path, optional
        A second slide to compare against the single input slide.
    config : CountCellsConfig, optional
        Complete settings, or give fields as keywords (``label="CD8"``).

    Returns
    -------
    Result
        One ``"count"`` item per results JSON and ``"figure"`` items for
        comparison plots. ``summary["results"]`` lists each slide's counts;
        in comparison mode ``summary["result"]`` holds the paired counts.

    Examples
    --------
    >>> import rocqipath as rp
    >>> result = rp.count_cells("cd8_slides/", "results/", label="CD8", source_magnification=40)  # doctest: +SKIP
    >>> [r["total_positive"] for r in result.summary["results"]]  # doctest: +SKIP
    [1520, 877]
    """
    from rocqipath.counting.counter import PositiveCellCounter

    counter = PositiveCellCounter(config, output_dir=str(output_dir))
    if compare_to is not None:
        if len(inputs) != 1 or inputs[0].is_dir():
            raise ValueError("compare_to= compares one slide with one slide; pass a single input file")
        result = counter.count_slide_pair(
            str(inputs[0]),
            str(compare_to),
            label=config.label,
            save_plots=config.save_plots,
            max_plots=config.max_plots,
            dpi=config.dpi,
        )
        summary: Dict[str, Any] = {"result": result}
    elif len(inputs) == 1 and inputs[0].is_dir():
        summary = {"results": counter.count_batch(str(inputs[0]), label=config.label)}
    else:
        summary = {"results": [counter.count_slide(str(p), label=config.label) for p in inputs]}
    root = output_dir / "cell_counting"
    items: List[Item] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.parent == root:
            continue
        role = "figure" if path.suffix.lower() == ".png" else "count"
        items.append(Item(sample_id=path.parent.name, role=role, path=path))
    return items, summary


# ── Figures ─────────────────────────────────────────────────────────────────


@workflow(
    "compare",
    config=CompareConfig,
    extra="viz",
    inputs=InputSpec(kind="three slides: H&E, ground-truth IHC and predicted IHC"),
)
def compare(inputs: List[Path], output_dir: Path, *, config: CompareConfig) -> Outputs:
    """Make publication figures comparing H&E, ground-truth IHC and predicted IHC.

    Saves one full-view figure with the three slides side by side, plus
    zoomed crops of the same box in all three at each requested anchor and
    zoom, and optionally random tissue crops (with their coordinates in a
    JSON sidecar). Existing figures are kept, so interrupted runs resume.

    Parameters
    ----------
    inputs : list of three paths, or one manifest JSON
        ``[he, ground_truth, prediction]`` image paths, or a case manifest
        whose ``stains`` hold ``gt_he``, ``gt_ihc`` and ``prediction_ihc``.
    output_dir : path
        Figures go directly into this folder, named after ``figure_name``.
    config : CompareConfig, optional
        Complete settings, or give fields as keywords (``zooms=["20x"]``).

    Returns
    -------
    Result
        One ``"figure"`` item per saved figure.

    Examples
    --------
    >>> import rocqipath as rp
    >>> rp.compare(["he.tif", "cd8.tif", "cd8_pred.tif"], "figures/", dpi=300)  # doctest: +SKIP
    """
    from rocqipath.viz.comparison import visualize_side_by_side

    if len(inputs) == 1 and inputs[0].suffix.lower() == ".json":
        from rocqipath.io.manifest import load_manifest

        stains = load_manifest(str(inputs[0]))["stains"]
        paths = [stains["gt_he"], stains["gt_ihc"], stains["prediction_ihc"]]
    elif len(inputs) == 3:
        paths = [str(p) for p in inputs]
    else:
        raise ValueError("compare expects [he, ground_truth, prediction] or one manifest JSON")
    visualize_side_by_side(
        *paths,
        str(output_dir / config.figure_name),
        config.dpi,
        config.title_reference,
        config.title_truth,
        config.title_prediction,
        regions=list(config.regions),
        zoom_sizes=config.zoom_sizes(),
        n_random_rois=config.random_rois,
        roi_seed=config.roi_seed,
        add_scale_bars=config.scale_bars,
        mpp=config.mpp,
    )
    stem = Path(config.figure_name).stem
    items = [
        Item(sample_id=Path(paths[0]).stem, role="figure", path=path)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name.startswith(stem)
    ]
    return items, {"figures": len(items)}


@workflow(
    "overlay_markers",
    config=OverlayConfig,
    extra="viz",
    inputs=InputSpec(kind="a case folder with one subfolder per marker, or a folder of cases"),
)
def overlay_markers(inputs: List[Path], output_dir: Path, *, config: OverlayConfig) -> Outputs:
    """Layer color masks of several IHC markers over a base marker.

    Each case folder holds one subfolder of patches per marker with the
    same filenames. For every shared filename, each marker's stain is
    turned into a colored mask and the combinations in ``config`` are
    rendered as composite and/or grid figures.

    Parameters
    ----------
    inputs : path
        One case folder, or a folder whose subfolders are cases.
    output_dir : path
        Figures go to ``<output_dir>/visualization/<case>/``.
    config : OverlayConfig
        Markers and combinations to draw; these have no defaults.

    Returns
    -------
    Result
        One ``"figure"`` item per saved figure. ``summary`` has
        ``patches_processed`` and ``figures_saved`` (per case for a batch).

    Examples
    --------
    >>> import rocqipath as rp
    >>> rp.overlay_markers(  # doctest: +SKIP
    ...     "case01/", "figures/",
    ...     markers={"he": rp.MarkerProfile(color=(0, 0, 255)), "cd8": rp.MarkerProfile(color=(255, 0, 0))},
    ...     combinations=[rp.OverlayCombo(base="he", overlays=["cd8"])],
    ...     base_marker="he",
    ... )
    """
    from rocqipath.viz.overlays import process_ihc_overlay

    summary: Dict[str, Any] = {}
    for folder in inputs:
        result = process_ihc_overlay(str(folder), config, str(output_dir))
        summary.update(result if len(inputs) == 1 else {folder.name: result})
    root = output_dir / "visualization"
    items = [Item(sample_id=path.parent.name, role="figure", path=path) for path in _files(root)]
    return items, summary


__all__ = [
    "align",
    "compare",
    "count_cells",
    "extract_patches",
    "extract_tissue",
    "extract_tma",
    "normalize_stain",
    "overlay_markers",
    "train_stain_normalizer",
]
