# Extract TMA cores from an 80x scan

**Goal:** turn a tissue microarray slide into one image per core, at a
consistent physical magnification.

**You need:** the `extraction` extra.

## The magnification trap

TMA slides are often scanned at 80x while whole sections are scanned at 40x. If
you extract by pyramid level, cores and sections end up at different physical
resolutions and are not comparable — silently.

Ask for a magnification instead:

```toml
default_magnification = 20.0
```

If the scanner wrote no objective tag, say so once, per slide:

```toml
[overrides."TMA12-A3__he__s01"]
source_magnification = 80.0
note = "Scanner wrote no objective-power tag."
```

`rocqipath study survey` finds every slide with this problem in one pass.

## With a study

```console
$ rocqipath study plan mystudy --set tissue.mode=tma
$ rocqipath study run mystudy --stage tissue
```

## Without a study

```python
from rocqipath.extraction import CoreExtractionConfig, run_core_extraction_pipeline

run_core_extraction_pipeline(
    input_dir="./data/tma",
    output_root="./results",
    cfg=CoreExtractionConfig(
        target_magnification=20.0,
        detection_magnification=1.25,
        source_magnification=80.0,      # omit when metadata is present
        only_circles=True,
        min_circularity=0.60,
        per_stain_detection=True,
        fallback_to_he=True,
    ),
    target_stains=["H&E", "CD8", "CD31"],
)
```

`target_stains` also accepts custom biomarker names that are not in the
built-in keyword list.

## Tuning detection

| Setting | Raise it when | Lower it when |
| --- | --- | --- |
| `min_circularity` | Debris and folds are detected as cores | Genuine cores with torn edges are missed |
| `min_area_fraction` | Small artifacts survive detection | Small cores are dropped |
| `box_scale` | Cores are clipped at the edge | Neighbouring cores bleed into the crop |
| `detection_magnification` | Detection misses fine structure | Detection is slow on large arrays |

`per_stain_detection` runs Otsu per stain, which handles IHC slides whose
background differs from H&E. `fallback_to_he` recovers when a stain's detected
core count disagrees with the reference — useful when a faint biomarker hides
part of the array.

## Output

```
results/tissue/TMA12-A3/
├── region_001.tif
├── region_001_preview.jpg
├── region_001_manifest.json
└── TMA12-A3_manifest.json
```

Each region manifest carries relative and absolute (level-0) coordinates,
detection source, and `output_magnification` — which downstream RocqiPath
readers pick up automatically, so a derived image never loses track of its
zoom.

Check the previews before running anything downstream. Detection problems are
obvious in a preview grid and invisible in a patch count.
