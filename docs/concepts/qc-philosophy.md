# QC philosophy: measure, then decide

## The problem with a threshold argument

A conventional patch extractor takes `tissue_threshold=0.5` and writes only the
tiles that pass. It seems reasonable until you want 0.6.

Then you re-extract. Hours of reading, decoding, and resizing, to produce a
strict subset of tiles you already had. Worse, the tiles that failed the old
threshold are gone, so you cannot even tell how many you lost or what they
looked like. And when a reviewer asks which threshold produced Figure 3, the
answer lives in whichever version of whichever script you happened to run.

## The inversion

**Expensive stages measure. Cheap steps decide.**

Patch extraction writes every tile it produced and records, per tile, the
properties a QC rule might care about:

```json
{"uid": "CASE-001__cd8__s01__x04096_y02048", "case": "CASE-001", "stain": "cd8",
 "x0": 4096, "y0": 2048, "tissue_fraction": 0.62, "blur": 118.4, "mean_od": 0.31}
```

No threshold has been applied. Then:

```console
$ rocqipath study select mystudy strict --min tissue_fraction=0.6
```

That evaluates the rule over the manifest and saves the matching identifiers,
the rule text, the recipe hash, and a timestamp. Two seconds. The tiles never
move.

## What this buys

**Changing your mind is free.** A different threshold is a different selection,
computed in seconds over a manifest you already have.

**Selections accumulate rather than overwrite.** `loose`, `strict`, and
`sharp` coexist. You can compare them, and you can report the comparison.

**Methods sections become precise.** "Patches were filtered using selection
`strict` (`tissue_fraction >= 0.6`), recipe `4f2a9c1e77b0`" is a complete,
checkable statement. `tissue_threshold=0.6` in a script is not.

**Rejected artifacts remain visible.** You can ask how many tiles a rule
discarded, and inspect them. That question is unanswerable once a filter has
been baked into extraction.

**Counting inherits the same property.** Counts are stored per patch, so a
slide-level density is an aggregation over a selection. Change the QC rule and
the density recomputes — without counting a single cell again.

## The rule language

Small and deliberately boring, evaluated through a whitelisted AST walk rather
than `eval`:

```
tissue_fraction >= 0.6 and blur >= percentile('blur', 10)
0.4 <= tissue_fraction < 0.9
stain in ["cd8", "cd31"] and not is_null(mean_od)
```

Comparisons, chaining, boolean logic, membership, arithmetic, and three
helpers. No imports, no attribute access, no calls beyond the helpers. A rule
lives in a JSON file and gets re-evaluated later, so it must be safe to read
from disk and impossible to turn into code execution.

See the [selections reference](../reference/selections.md) for the full grammar.

## Where thresholds still belong

Detection thresholds that determine *what gets computed at all* — minimum core
area, circularity for TMA cores, registration quality gates — stay in the
recipe. They change what is produced, not which of the produced artifacts you
choose to keep. The distinction is worth holding onto: recipe settings change
the pixels; selections change the sample.
