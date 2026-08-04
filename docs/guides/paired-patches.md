# Extract paired patches

**Goal:** produce spatially corresponding H&E and IHC tiles on one coordinate
grid, ready for training or analysis.

**You need:** the `extraction` extra, and alignment already run.

## With a study

```console
$ rocqipath study run mystudy --stage patches
```

Inputs resolve from the index and the alignment output. Nothing needs a path.

Extraction writes **every** tile and records its properties. It applies no
tissue threshold — that decision belongs to a
[selection](../reference/selections.md), which is what makes it changeable
later.

## Without a study

```python
from rocqipath.extraction import PatchExtractionConfig, run_patch_extraction

run_patch_extraction(PatchExtractionConfig(
    he_dir="./data/reference",
    aligned_dir="./results/alignment",
    output_dir="./results",
    biomarker_folders=["CD8"],
    he_filename_pattern=r"^(?P<sample_id>.+?)_he\.tiff?$",
    patch_size=512,
    stride=512,
    tissue_threshold=0.0,          # measure now, decide later
    target_magnification=20.0,
    max_workers=4,
))
```

## Grid geometry

`patch_size` and `stride` are both in target-grid pixels, at the magnification
you requested.

- `stride == patch_size` — tiles abut, no overlap. The default, and the right
  choice for most analysis.
- `stride < patch_size` — tiles overlap. Useful for training augmentation and
  for reconstructing continuous predictions, at a cost in count and disk.

## The canvas check

Before sampling, RocqiPath confirms that the reference and moving canvases
agree at the target magnification, within `dimension_tolerance` (1% by
default). A mismatch is an error, not a silent crop.

This check is worth understanding rather than raising past. A 1% disagreement
at 20x across a 40 mm section is about 200 micrometres — enough to shift a tile
into neighbouring tissue while every patch still looks plausible.

When it fires, the cause is almost always upstream: two slides resolved to
different physical magnifications, or an alignment export written on a
different canvas. Check `survey/` before touching the tolerance.

## Applying quality control

```console
$ rocqipath study select mystudy strict --min tissue_fraction=0.6

  Selection: strict
    kept       8412 / 12905  (65.2%)
    tissue_fraction  min=0.6 median=0.81 max=1
```

Drop the blurriest tenth of the cohort as well:

```console
$ rocqipath study select mystudy sharp \
      --rule "tissue_fraction >= 0.6 and blur >= percentile('blur', 10)"
```

Both selections coexist. The tiles never move. Cite the selection name and the
recipe hash in your methods section.

## Parallelism

`max_workers` above 1 helps when decoding dominates. It does not help when the
bottleneck is a network filesystem — in that case, stage to local disk first,
or reduce `stride` overlap so fewer reads are needed.
