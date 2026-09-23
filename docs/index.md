# RocqiPath

RocqiPath processes whole-slide images for computational pathology: it cuts
out tissue and tissue-microarray cores, aligns IHC slides onto H&E, extracts
matching patch pairs, normalizes stains, counts DAB-positive cells and makes
quality-control and publication figures.

```python
import rocqipath as rp

regions = rp.extract_tissue("slides/", "results/regions", target_magnification=10)
aligned = rp.align("pairs/", "results/aligned", backend="orb")
patches = rp.extract_patches(aligned, "results/patches", patch_size=512)
counts = rp.count_cells(aligned, "results/counts", label="CD8")
```

## One pattern for everything

Every workflow is called the same way:

```python
result = rp.<workflow>(inputs, output_dir, *, config=None, **settings)
```

- **`inputs`**: what to process. Files, folders, or the result of an earlier
  workflow.
- **`output_dir`**: where results go. Every run records what it made in
  `output_dir/rocqipath.json`.
- **`settings`**: any field of the workflow's config class, for example
  `target_magnification=10`, or a whole `config=rp.AlignConfig(...)`.
- **The return value** is a [`Result`](reference/results.md) listing every file produced.

The same workflows are available as commands (`rocqipath align --help`) and
in [Studio](studio.md), a local browser workspace.

| Workflow | What it does |
|---|---|
| [`extract_tissue`](workflows/extract-tissue.md) | Cut each piece of tissue out of whole-slide images |
| [`extract_tma`](workflows/extract-tma.md) | Cut TMA cores out of H&E slides and matching IHC slides |
| [`align`](workflows/align.md) | Register IHC (moving) slides onto H&E (reference) slides |
| [`extract_patches`](workflows/extract-patches.md) | Save pixel-matched patch pairs from aligned slides |
| [`train_stain_normalizer`](workflows/stain.md) / [`normalize_stain`](workflows/stain.md) | Match stain colors to a reference |
| [`count_cells`](workflows/count-cells.md) | Count DAB-positive cells, per slide or as a comparison |
| [`compare`](workflows/compare.md) | Publication figures of H&E, true IHC and predicted IHC |
| [`overlay_markers`](workflows/overlay-markers.md) | Layer several IHC markers as colored masks |

New here? Start with [Getting started](getting-started.md), then read about
[magnification](concepts/magnification.md). It is the one concept every workflow uses.

!!! warning "Patient data"
    Whole-slide images and filenames may contain patient information. Keep
    data outside the repository and never attach it to public issues.
