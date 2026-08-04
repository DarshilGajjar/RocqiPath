# RocqiPath documentation

Four sections, split by what you are trying to do right now.

| If you want to… | Go to |
| --- | --- |
| install it and run something end to end | **[Get started](start/)** |
| accomplish a specific task | **[Guides](guides/)** |
| look up a format, flag, or error | **[Reference](reference/)** |
| understand why it works this way | **[Concepts](concepts/)** |

Short answers to recurring questions live in the [FAQ](faq.md).

---

## Get started

- [Installation](start/install.md) — Python, extras, and the workspace root
- [Native dependencies](start/native-dependencies.md) — libvips and OpenSlide, per OS
- [Your first study](start/first-study.md) — two slides, end to end, in ten minutes
- [Migrating to studies](start/migrating-to-studies.md) — from explicit paths, without breaking anything

## Guides

- [Align an H&E/IHC pair](guides/align-he-ihc-pair.md)
- [Extract TMA cores from an 80x scan](guides/extract-tma-cores.md)
- [Extract paired patches](guides/paired-patches.md)
- [Normalise stains](guides/stain-normalization.md)
- [Count DAB-positive cells](guides/count-dab-cells.md)
- [Resume, scale, and re-run](guides/resume-and-scale.md)

## Reference

- [`study.toml`](reference/study-toml.md) — the descriptor you write
- [`recipe.json`](reference/recipe-json.md) — the resolved plan
- [Manifests](reference/manifests.md) — the measurement substrate
- [Selections](reference/selections.md) — the QC rule language
- [CLI](reference/cli.md) — every command and flag
- [Python API](reference/python-api.md) — `Study` and the pipeline functions
- [Errors](reference/errors.md) — message, cause, fix

## Concepts

- [Magnification, not pyramid levels](concepts/magnification.md)
- [Survey, recipe, run](concepts/survey-recipe-run.md)
- [Coordinates and canvases](concepts/coordinates-and-canvases.md)
- [QC philosophy: measure, then decide](concepts/qc-philosophy.md)
- [Architecture](concepts/architecture.md) — module layout and import rules

## Quality control

- [QC gallery](qc-gallery/) — what good and bad output looks like

## Notebooks

The eight notebooks in [`how_to_use/`](../how_to_use/) demonstrate the pipeline
functions directly, from installation through an end-to-end H&E/CD8 workflow.
They remain a supported way to use RocqiPath — especially for exploration,
where a workspace would be overhead.
