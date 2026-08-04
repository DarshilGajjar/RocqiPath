# Python API reference

Two layers, both supported. The `Study` facade resolves inputs for you; the
pipeline functions take explicit paths and have not changed.

## `Study`

```python
from rocqipath import Study
```

### Construction

| Call | Meaning |
| --- | --- |
| `Study.create(name, sources=[...], stains=[...], home=None, default_magnification=20.0, overwrite=False)` | Create the directory and write `study.toml`. |
| `Study.open(name, home=None)` | Open an existing study. Raises `StudyNotFoundError` (a `FileNotFoundError`). |

`home` defaults to `$ROCQIPATH_HOME`, then `~/rocqipath`.

### Index and identity

| Call | Returns |
| --- | --- |
| `study.index(stat_files=True, write=True)` | `list[SlideRecord]` — discovers slides and writes `index.jsonl`. |
| `study.slides(refresh=False)` | `list[SlideRecord]` — reads the stored index unless refreshed. |
| `study.pairs(biomarkers=None)` | `list[SlidePair]` — derived, never stored. |
| `study.cases()` | `list[str]` |
| `study.index_warnings` | `list[str]` — filenames that did not match, undeclared stains. |

### Survey, verify, plan

| Call | Returns |
| --- | --- |
| `study.survey(write=True, progress=None)` | `StudySurvey` |
| `study.load_survey()` | `StudySurvey \| None` |
| `study.verify()` | `VerificationReport` — `.ok`, `.errors`, `.warnings`, `.format()` |
| `study.plan(overrides=None, write=True)` | `Recipe` |
| `study.recipe()` | `Recipe` — stored plan, building one if absent. |

### Running

```python
results = study.run(["alignment", "patches"], dry_run=False, link_mode="auto")
for result in results:
    print(result.stage, result.status, result.n_items, result.error)
```

`stages` accepts a string, a sequence, or `None` for everything. Stages always
execute in dependency order regardless of the order requested.

### Selections and results

| Call | Returns |
| --- | --- |
| `study.manifest(stage, name=None)` | `list[dict]` |
| `study.select(name, stage="patches", rule="", **thresholds)` | `Selection` |
| `study.selection(name)` | `Selection` |
| `study.selections()` | `list[str]` |
| `study.results(stage="counts", selection=None, group_by=("case", "stain"), ...)` | `ResultTable` |

`ResultTable` offers `.to_dicts()`, `.to_csv(path)`, `.format(limit=20)`, and
`.to_dataframe()` — the last requires pandas, which RocqiPath deliberately does
not depend on.

### Introspection

```python
study.name, study.root, study.paths, study.descriptor
study.summary()     # counts, which artifacts exist, selections present
study.reload()      # drop cached descriptor and index state
```

## Pipeline functions

Unchanged. Use these directly for a single slide, an exploratory notebook, or
any script that already works.

### Tissue and cores

```python
from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

run_tissue_pipeline(
    input_dir="./data/wsi",
    output_dir="./results",
    cfg=TissueExtractionConfig(
        target_magnification=20.0,
        detection_magnification=1.25,
        min_area_fraction=0.005,
    ),
)
```

```python
from rocqipath.extraction import CoreExtractionConfig, run_core_extraction_pipeline

run_core_extraction_pipeline(
    input_dir="./data/tma",
    output_root="./results",
    cfg=CoreExtractionConfig(
        target_magnification=20.0,
        source_magnification=80.0,      # omit when metadata is present
        only_circles=True,
        min_circularity=0.60,
    ),
    target_stains=["H&E", "CD8", "CD31"],
)
```

### Alignment

```python
from rocqipath.registration import AlignmentConfig, run_alignment

run_alignment(AlignmentConfig(
    input_dir="./data/pairs",
    output_dir="./results",
    alignment_method="valis",           # or "orb"
    target_magnification=20.0,
    qc_enabled=True,
))
```

Expected input layout:

```
data/pairs/<biomarker>/he/<sample>_he.<ext>
data/pairs/<biomarker>/ihc/<sample>_<biomarker>.<ext>
```

Set `dry_run=True` to validate discovery and pairing on a base install.

### Paired patches

```python
from rocqipath.extraction import PatchExtractionConfig, run_patch_extraction

run_patch_extraction(PatchExtractionConfig(
    he_dir="./data/reference",
    aligned_dir="./results/alignment",
    output_dir="./results",
    biomarker_folders=["CD8"],
    patch_size=512,
    stride=512,
    target_magnification=20.0,
))
```

### Stain normalisation and counting

```python
from rocqipath.stain import (
    StainNormalizationConfig,
    run_stain_normalization_apply,
    run_stain_normalization_train,
)

cfg = StainNormalizationConfig(n_type="macenko", stains=["he"])
run_stain_normalization_train("./patches", "./results", cfg)
run_stain_normalization_apply("./patches", "./results", cfg)
```

```python
from rocqipath.analysis import PositiveCellCounter

counter = PositiveCellCounter({
    "output_dir": "./results",
    "target_magnification": 20.0,
    "patch_size": 512,
})
counter.count_slide("./data/cd8.svs", label="CD8")
```

Cell-density tissue area is measured from the same per-pixel tissue mask used
for patch acceptance, so background pixels inside an accepted tile are excluded
from the denominator.

## Core building blocks

```python
from rocqipath.core.slide import SlideReader
from rocqipath.core.magnification import build_magnification_plan
from rocqipath.core.output import OutputLayout
```

`SlideReader` reads target-grid coordinates at an exact physical magnification.
`OutputLayout` builds the `<root>/<module>/<item>` hierarchy every module uses.

## Package layout

```
src/rocqipath/
├── study/            study.toml, index, survey, recipe, manifests, selections
├── core/             magnification, slide reader, output layout, logging
├── registration/     VALIS and ORB alignment
├── extraction/       WSI, TMA/core, and paired patches
├── stain/            Reinhard, Macenko, Vahadane
├── analysis/         positive-cell counting
├── visualization/    grids, paired QC, IHC overlays, comparisons
├── config/           typed pipeline configurations
└── cli/              command-line interface
```

Primary symbols are re-exported from each subpackage. Import private helpers
whose names begin with `_` only when extending RocqiPath itself.
