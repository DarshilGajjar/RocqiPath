# Your first study

Ten minutes, two slides, from a bare install to a result table. You need the
`orb` and `cellcount` extras and the native runtimes from
[native dependencies](native-dependencies.md).

## 1. Put two slides somewhere RocqiPath can see them

Any directory works — a study never writes to it. For this walkthrough:

```
/mnt/archive/demo/
├── CASE-001_he.svs
└── CASE-001_cd8.svs
```

The filenames matter, because they carry identity. The default pattern reads
`<case>_<stain>[_s<NN>].<ext>`, so those two files become one case with an
H&E and a CD8 slide. If your archive uses a different convention, you change
one regex in `study.toml` rather than renaming gigabytes of files.

## 2. Create the study

```console
$ rocqipath study init demo --source /mnt/archive/demo --stain he --stain cd8
```

That writes `$ROCQIPATH_HOME/demo/study.toml` — the only file you author by
hand. The first `--stain` becomes the reference stain, the registration target
every other stain is warped onto.

Open it and you will find the pattern, the stain roles, the default
magnification, and a commented `[overrides]` block. Everything else under the
study directory is generated and safe to delete and rebuild.

## 3. Index the slides

```console
$ rocqipath study index demo

  Indexed 2 slide(s) across 1 case(s).
    cd8          1
    he           1
    pairs        1

  Wrote /data/rocqipath/demo/index.jsonl
```

Each slide now has a `slide_uid` of the form `CASE-001__cd8__s01`. A double
underscore separates the fields, so case identifiers containing single
underscores — which hospital accession numbers usually do — parse correctly.

Note that `pairs` is derived, not stored. One H&E can serve every biomarker in
the cohort without ever being duplicated on disk.

## 4. Survey them

```console
$ rocqipath study survey demo

    [1/2] CASE-001__cd8__s01                 40x            ok
    [2/2] CASE-001__he__s01                  40x            ok

  Surveyed 2 slide(s).
    readable                2
    missing magnification   0
    below target            0
    magnifications          {'40x': 2}
```

The survey opens each slide once at low cost and records what it actually is:
objective magnification, microns per pixel, pyramid downsamples, dimensions,
vendor. No tile is read at full resolution.

If a slide reports `no metadata`, its scanner wrote no objective-power tag.
Add the value under `[overrides]` in `study.toml`:

```toml
[overrides."CASE-001__he__s01"]
source_magnification = 80.0
note = "Scanner wrote no objective-power tag."
```

## 5. Verify before spending an hour

```console
$ rocqipath study verify demo

Study: demo
  cases: 1
  slides active: 2
  slides indexed: 2
  slides surveyed: 2
  stains declared: 2

No problems found. This study is ready to run.
```

This is the cheapest useful command in RocqiPath. It catches missing files,
cases with no reference slide, slides scanned below your requested
magnification, and stains found on disk but never declared — in seconds,
before anything expensive starts.

Anything reported as an error blocks a run and comes with the exact edit that
resolves it.

## 6. Resolve a plan

```console
$ rocqipath study plan demo

  Wrote /data/rocqipath/demo/recipe.json
  Recipe hash: 4f2a9c1e77b0

  Stages:
    tissue       enabled
    alignment    enabled
    patches      enabled
    stain        enabled
    counts       enabled
```

`recipe.json` holds fully resolved settings for every stage — nothing left as
"auto", nothing for a pipeline to guess at run time. Read it, edit it, commit
it. Want a different patch size?

```console
$ rocqipath study plan demo --set patches.patch_size=256
```

Every artifact records the recipe hash it was produced under, so a stage can
tell whether existing output is still current.

## 7. Dry-run, then run

```console
$ rocqipath study run demo --dry-run
```

A dry run resolves every input and configuration and prints what would happen,
without touching a pixel. Once it looks right:

```console
$ rocqipath study run demo --stage alignment --stage patches
```

## 8. Apply QC as a saved view

Patch extraction wrote every tile it produced, along with the properties a QC
rule might care about — and applied no threshold of its own. Thresholds are a
separate, cheap step:

```console
$ rocqipath study select demo strict --min tissue_fraction=0.6

  Selection: strict
    rule       tissue_fraction >= 0.6
    stage      patches
    kept       8412 / 12905  (65.2%)
```

Change your mind and make a second selection. The first one stays, the tiles
never move, and a methods section can name exactly which selection produced a
figure:

```console
$ rocqipath study select demo sharp \
      --rule "tissue_fraction >= 0.5 and blur >= percentile('blur', 10)"
```

## 9. Read the table

```console
$ rocqipath study results demo --selection strict --csv results.csv
```

## Next

- [Align an H&E/IHC pair](../guides/align-he-ihc-pair.md)
- [Count DAB-positive cells](../guides/count-dab-cells.md)
- [Why physical magnification](../concepts/magnification.md)
