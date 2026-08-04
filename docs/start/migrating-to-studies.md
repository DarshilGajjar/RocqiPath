# Migrating to studies

**Nothing you already have breaks.** Every pipeline function keeps its
signature and its behaviour. Studies are a layer on top, not a replacement.

```python
# This still works, unchanged, and always will.
from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

run_tissue_pipeline(
    input_dir="./data/wsi",
    output_dir="./results",
    cfg=TissueExtractionConfig(target_magnification=20.0),
)
```

## What a study adds

| Doing it by hand | With a study |
| --- | --- |
| Each pipeline takes different path arguments | No pipeline takes a path |
| Chaining requires knowing the previous stage's internal layout | Stages resolve inputs from the index |
| Cohort facts restated per call as `target_stains`, `biomarker_folders`, `he_channel_name` | Declared once in `study.toml` |
| `source_magnification` is a global setting | A per-slide `[overrides]` entry |
| One H&E duplicated under every biomarker folder | Pairs derived; nothing duplicated |
| Settings live in whichever script you ran | Resolved into a hashed `recipe.json` |
| A threshold change means re-extracting | A threshold change is a new selection |

## Migrating an existing workflow

**1. Describe the cohort instead of the directory.** If your script globbed
`./data/pairs/cd8/he/*.svs`, point a source at the archive and let the pattern
decode identity:

```toml
[[sources]]
root = "/mnt/archive/crc_2024"
pattern = '(?P<case>.+?)_(?P<stain>he|cd8|cd31)\.(svs|ndpi|tif)$'
```

You do not have to rename anything. Adjust the regex to the names you already
have.

**2. Move per-call settings into the recipe.** Run `rocqipath study plan`, open
`recipe.json`, and set the values your script used to pass. They are now
versioned with the study rather than buried in a script.

**3. Drop your QC thresholds to zero.** In the study model, extraction
measures and a selection decides. Leave `patches.tissue_threshold` at `0.0`
and reproduce your old behaviour with:

```console
$ rocqipath study select mystudy legacy --min tissue_fraction=0.5
```

You get the same tiles, plus the ability to change the threshold later without
re-extracting.

**4. Keep your notebooks.** The eight notebooks in `how_to_use/` still run.
They demonstrate the pipeline functions directly, which remains a supported
way to use RocqiPath — especially for one-off exploration where a workspace
would be overhead.

## When to use which

**Use the pipeline functions directly** for a single slide, an exploratory
notebook, or a script that already works.

**Use a study** for anything with more than a handful of slides, anything you
will re-run, and anything you intend to publish — the recipe hash and saved
selections are what make a result reproducible months later.

## Mixing the two

A study writes into the same `<root>/<module>/<item>` layout the pipelines
always used, so the trees are interchangeable. You can run a study through
`alignment`, then point a hand-written script at
`$ROCQIPATH_HOME/mystudy/alignment/` and carry on as before.
