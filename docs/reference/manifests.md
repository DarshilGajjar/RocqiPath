# Manifests

A manifest records **measurements**, never decisions. Every stage writes one
alongside its artifacts, listing what it produced and the properties a QC rule
might later care about — with no thresholds applied.

This is what makes [selections](selections.md) cheap.

## Files

Two per manifest, in the stage directory:

```
patches/
├── patches.jsonl           one JSON object per artifact
└── patches.manifest.json   sidecar: stage, recipe hash, row count, fields
```

JSONL rather than a JSON array, because patch-level manifests reach millions of
rows and an array can neither be streamed nor appended.

## Sidecar fields

| Key | Meaning |
| --- | --- |
| `stage` | Stage that produced the rows. |
| `study` | Study name. |
| `recipe_hash` | Recipe the rows were produced under. |
| `rocqipath_version` | Package version at write time. |
| `generated_at` | UTC timestamp. |
| `n_rows` | Number of records. |
| `fields` | Field names observed across the rows. |
| `extra` | Free-form stage-specific metadata. |

## Row conventions

Every row should carry a `uid`. Selections store identifiers, so a row without
one cannot be selected.

Recommended identity fields, present wherever meaningful: `uid`, `case`,
`stain`, `slide_uid`.

Patch rows additionally carry level-0 position (`x0`, `y0`), the target-grid
`size`, and measured properties:

```json
{"uid": "CRC-118__cd8__s01__x04096_y02048",
 "slide_uid": "CRC-118__cd8__s01", "case": "CRC-118", "stain": "cd8",
 "x0": 4096, "y0": 2048, "size": 512, "magnification": 20.0,
 "tissue_fraction": 0.62, "blur": 118.4, "mean_od": 0.31}
```

Positions are stored in level-0 coordinates on purpose: they remain valid if
the same region is later re-extracted at a different magnification, which
target-grid coordinates would not. See
[coordinates and canvases](../concepts/coordinates-and-canvases.md).

## Reading

```python
from rocqipath.study import read_manifest, read_manifest_info, summarise_field

rows = list(read_manifest("patches/patches.jsonl"))
info = read_manifest_info("patches/patches.manifest.json")

print(info.n_rows, info.recipe_hash)
print(summarise_field(rows, "tissue_fraction"))
# {'count': 12905.0, 'min': 0.0, 'max': 1.0, 'mean': 0.41, 'median': 0.38}
```

Or through a study, which resolves the path for you:

```python
rows = study.manifest("patches")
```

## Writing

If you are adding a stage, use the context manager so the sidecar is written
even when the stage raises part-way through:

```python
from rocqipath.study import ManifestWriter

with ManifestWriter(
    output_dir, "patches",
    stage="patches", study=study.name, recipe_hash=recipe.recipe_hash,
) as writer:
    for tile in tiles:
        writer.write({
            "uid": tile.uid, "case": tile.case, "stain": tile.stain,
            "x0": tile.x0, "y0": tile.y0, "size": tile.size,
            "tissue_fraction": tile.tissue_fraction, "blur": tile.blur,
        })
```

Two rules for new stages:

1. **Write every artifact.** Filtering belongs in a selection.
2. **Write measurements, not verdicts.** Record `tissue_fraction: 0.62`, never
   `accepted: true`. A verdict is one rule's opinion, frozen; a measurement
   supports every rule anyone writes later.
