# Selections

A selection is a named QC view over a stage manifest: a saved rule, the
identifiers it matched, the recipe hash, and a timestamp. It stores no pixels
and moves no files.

See [QC philosophy](../concepts/qc-philosophy.md) for why.

## Creating one

```console
$ rocqipath study select mystudy strict --min tissue_fraction=0.6
$ rocqipath study select mystudy sharp \
      --rule "tissue_fraction >= 0.5 and blur >= percentile('blur', 10)"
```

```python
study.select("strict", tissue_fraction=0.60)
study.select("sharp", rule="blur >= percentile('blur', 10)")
study.select("both", rule="blur >= 10", tissue_fraction=0.6)   # combined with and
```

Keyword arguments are inclusive minimums. When both a rule and keywords are
given they are joined with `and`.

## The rule language

Evaluated through a whitelisted AST walk, never `eval`. Rules are stored in
JSON and re-read later, so reading one must not be able to execute code.

| Feature | Example |
| --- | --- |
| Field reference | `tissue_fraction` |
| Comparison | `blur > 10`, `stain == "cd8"` |
| Chained comparison | `0.4 <= tissue_fraction < 0.9` |
| Boolean logic | `a >= 1 and (b < 2 or not c)` |
| Membership | `stain in ["cd8", "cd31"]` |
| Arithmetic | `positive_cells / area_mm2 > 50` |
| Conditional | `blur if stain == "he" else 0` |

### Helpers

| Helper | Meaning |
| --- | --- |
| `percentile(field, q)` | The `q`-th percentile of `field` across the whole manifest, linearly interpolated. |
| `is_null(value)` | Whether a field is missing. |
| `lower(value)` | Lowercase a string; other types pass through. |

`percentile` is computed over the manifest being filtered, so
`blur >= percentile('blur', 10)` means "drop the blurriest tenth of this
cohort" rather than a fixed number that will not transfer between scanners.

### Semantics worth knowing

**A missing field never satisfies a threshold.** A row without
`tissue_fraction` fails `tissue_fraction >= 0.5` rather than raising. This
keeps a heterogeneous manifest usable.

**Anything outside the grammar is rejected.** Imports, attribute access,
comprehensions, lambdas, and calls to anything but the three helpers raise
`RuleError`.

## What gets saved

`selections/<name>.json`:

| Key | Meaning |
| --- | --- |
| `name`, `study`, `stage` | Identity. |
| `rule` | The exact rule text evaluated. |
| `manifest` | Manifest path it was evaluated over. |
| `recipe_hash` | Recipe the manifest was produced under. |
| `created_at` | UTC timestamp. |
| `n_input`, `n_selected` | Rows considered and kept. |
| `stats` | Per-field min/max/mean/median over the selected rows. |
| `uids` | Identifiers of the selected artifacts. |

## Using one

```python
selection = study.selection("strict")
selection.n_selected, selection.fraction_kept
selection.contains("CRC-118__cd8__s01__x04096_y02048")

table = study.results(selection="strict")
```

```console
$ rocqipath study results mystudy --selection strict --csv results.csv
```

Because counts are stored per patch, a slide-level density is an aggregation
over a selection. Change the QC rule and the density recomputes without
counting a single cell again.

## Naming

Selections accumulate rather than overwrite, so name them for what they mean —
`strict`, `sharp`, `he-only`, `revision-2` — and cite the name in your methods
section alongside the recipe hash.
