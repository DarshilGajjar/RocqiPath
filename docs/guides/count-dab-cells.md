# Count DAB-positive cells

**Goal:** quantify chromogen-positive cells per slide, with a density that
holds up to a reviewer's questions.

**You need:** the `cellcount` extra.

## Declare the chromogen once

```toml
[stains.cd8]
role = "moving"
chromogen = "dab"
```

The counting stage acts on stains that declare a chromogen, so nothing has to
be listed again at run time.

```console
$ rocqipath study run mystudy --stage counts
```

## Without a study

```python
from rocqipath.analysis import PositiveCellCounter

counter = PositiveCellCounter({
    "output_dir": "./results",
    "target_magnification": 20.0,
    "patch_size": 512,
    "min_cell_area": 50,
})
counter.count_slide("./data/cd8.svs", label="CD8")
```

## The denominator is the hard part

A count is meaningless without an area, and the area is where most published
densities go wrong.

RocqiPath measures tissue area from the **same per-pixel tissue mask** used for
patch acceptance, and excludes background pixels inside an accepted tile from
the denominator. A tile that is 40% background contributes 60% of its area, not
100%.

This matters more than it sounds. Using tile area instead of tissue area
systematically deflates density at tissue edges — which is exactly where
immune infiltrate is often most interesting.

## Object size gates

`min_cell_area` and `max_cell_area` are in target-grid pixels, so they scale
with the magnification you requested. At 20x, a lymphocyte is roughly 40–120
pixels in area; at 40x, four times that.

Change the magnification and these need revisiting. The recipe records both
together, which is the point.

## Densities from a selection

Counts are stored per patch, so a slide-level density is an aggregation:

```console
$ rocqipath study select mystudy strict --min tissue_fraction=0.6
$ rocqipath study results mystudy --selection strict --csv cd8_density.csv
```

Change the QC rule and the density recomputes — without counting a single cell
again. That is the practical payoff of storing counts per patch rather than one
number per slide.

```python
table = study.results(
    stage="counts",
    selection="strict",
    group_by=("case", "stain"),
    sum_fields=("positive_cells", "tissue_area_um2"),
)
print(table.format())
table.to_csv("cd8_density.csv")
```

## Reporting

State four things and the result is reproducible:

1. the physical magnification (`20x`, not "level 1");
2. the recipe hash;
3. the selection name and its rule;
4. that density uses tissue area, not tile area.

For example: *"CD8+ density was computed at 20x under recipe `4f2a9c1e77b0`,
restricted to selection `strict` (`tissue_fraction >= 0.6`), with tissue area
measured from the per-pixel mask."*
