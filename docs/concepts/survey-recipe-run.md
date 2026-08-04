# Survey, recipe, run

RocqiPath separates three things that are usually tangled together: measuring
the data, deciding what to do with it, and doing it.

```
study.toml  ->  survey  ->  recipe  ->  stage output + manifests  ->  selections
(you write)     measured    decided     pixels + measurements        QC views
```

Each arrow is a file on disk. That is the point: every intermediate decision is
inspectable, editable, and diffable without reading any Python.

## study.toml — what you declare

Cohort-level facts that no amount of measurement can infer: where the slides
are, how filenames encode identity, which stain is the registration reference,
which chromogen a biomarker uses.

It is TOML because you write it by hand and comments matter. Everything
RocqiPath generates is JSON. The distinction is deliberate — file extension
tells you whether a file is yours to edit.

## survey — what the slides actually are

A cheap pass that opens every slide once and records objective magnification,
microns per pixel, pyramid downsamples, dimensions, and vendor. Nothing is read
at full resolution.

Its value is timing. Without it, "this slide has no objective metadata" and
"20x cannot be produced from a 10x scan" surface three hours into an overnight
run. With it, they surface in seconds — and `rocqipath study verify` turns them
into a list with the exact fix beside each one.

## recipe.json — what will be done

The survey and the descriptor are combined into a fully resolved plan. No
`None`, no "auto", nothing for a pipeline to work out at run time. It carries a
`recipe_hash` computed over the decision-bearing content only, so regenerating
an unchanged plan yields an unchanged hash.

This buys four things:

- **Review.** A collaborator can audit exactly what was run without reading
  code.
- **Editing.** Change one number, re-run. A two-line diff, not a code change.
- **Provenance.** Every artifact records the hash it was produced under.
- **Resumability.** A stage can tell whether existing output is still current,
  which matters when a run takes six hours.

## Stage output and manifests — measure, don't decide

Each stage writes its artifacts and a manifest recording, for every artifact,
the properties a QC rule might later care about — tissue fraction, blur,
optical density. It applies no thresholds.

This is the inversion that makes the model worth adopting. See
[QC philosophy](qc-philosophy.md).

## Selections — deciding afterwards

A selection is a named rule evaluated over a manifest, saved with its rule
text, recipe hash, and timestamp. It stores identifiers, not pixels.

Tightening a tissue threshold becomes a two-second operation instead of a
re-extraction, both selections stay on disk, and a paper can name the one that
produced each figure.

## The whole loop

```console
$ rocqipath study index  mystudy
$ rocqipath study survey mystudy
$ rocqipath study verify mystudy     # stop here if anything is red
$ rocqipath study plan   mystudy
$ rocqipath study run    mystudy --dry-run
$ rocqipath study run    mystudy
$ rocqipath study select mystudy strict --min tissue_fraction=0.6
$ rocqipath study results mystudy --selection strict --csv results.csv
```
