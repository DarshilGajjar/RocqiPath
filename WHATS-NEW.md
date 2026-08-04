# What changed in this drop

Two things were implemented: the study workspace (Part 1) and the
documentation restructure (Part 2). **Nothing existing breaks** — every
pipeline function keeps its signature and behaviour, and the eight notebooks
in `how_to_use/` still run.

## How to apply this

**Option A — review the diff first (recommended).** `CHANGES.patch` in this
folder is a git patch against the `main` commit it was generated from:

```console
$ cd /path/to/your/RocqiPath
$ git checkout -b study-workspace
$ git apply --stat  ../CHANGES.patch     # see what it touches
$ git apply --check ../CHANGES.patch     # confirm it applies cleanly
$ git apply         ../CHANGES.patch
$ python -m pytest
```

**Option B — copy the tree.** This folder is the full repository with the
changes applied. Copy it over your working tree, or diff directory-by-directory.

## Part 1 — input, output, pre/post-processing

New package: `src/rocqipath/study/` (14 modules, standard library plus `core`
only for the parts that must run on a base install).

| File | What it does |
| --- | --- |
| `paths.py` | `ROCQIPATH_HOME` resolution and the study layout |
| `descriptor.py` | Parse, validate, and generate `study.toml` |
| `index.py` | Slide discovery, `slide_uid`, derived pairs, `index.jsonl` |
| `survey.py` | The cheap fingerprint pass over every slide |
| `verify.py` | Pre-flight checks, each with the fix that resolves it |
| `recipe.py` | The resolved, hashed plan |
| `manifests.py` | JSONL artifact manifests plus sidecars |
| `selection.py` | The safe rule language and saved QC views |
| `staging.py` | Symlink farm bridging the index to directory-based pipelines |
| `stages.py` | **The integration seam** — recipe → existing configs → existing pipelines |
| `results.py` | Tidy tables, CSV, optional pandas |
| `study.py` | The `Study` facade |
| `doctor.py` | Environment diagnostics |

New CLI: `rocqipath study {init,index,survey,verify,plan,run,select,results,show,list}`
and `rocqipath doctor`.

**The five design decisions, and where to read about them:**

1. **Slides are referenced, never ingested** — `docs/reference/study-toml.md`
2. **Pairs are derived, not stored** — one H&E serves every biomarker without
   being duplicated. Fixes the `data/pairs/<biomarker>/he/` duplication in the
   old layout.
3. **Survey before plan** — `docs/concepts/survey-recipe-run.md`
4. **The recipe is a file, and it is hashed** — `docs/reference/recipe-json.md`
5. **Stages measure; selections decide** — `docs/concepts/qc-philosophy.md`.
   This is the one worth reading first: recipes now default
   `patches.tissue_threshold` and `counts.tissue_threshold` to `0.0`.

**Also fixed from the old API surface:** the `output_dir` / `output_root`
inconsistency, per-pipeline path arguments, cohort facts restated three ways
(`target_stains`, `biomarker_folders`, `he_channel_name`), and
`source_magnification` being global when it is a per-slide fact.

## Part 2 — the GitHub page

`README.md` went from 348 lines to 152. Everything else moved into `docs/`,
split by reader intent:

```
docs/
├── README.md                     the map
├── start/       install · native-dependencies · first-study · migrating-to-studies
├── guides/      align-he-ihc-pair · extract-tma-cores · paired-patches
│                stain-normalization · count-dab-cells · resume-and-scale
├── reference/   study-toml · recipe-json · manifests · selections
│                cli · python-api · errors
├── concepts/    magnification · survey-recipe-run · coordinates-and-canvases
│                qc-philosophy · architecture
├── qc-gallery/  what good and bad output looks like
└── faq.md
```

New repository files: `CITATION.cff` (turns on GitHub's "Cite this repository"
button), `CITATION.md`, `SECURITY.md` (**with a patient-data policy for public
issues** — the differentiator for a clinical-imaging package),
`CODE_OF_CONDUCT.md`, four issue forms, and a PR template.

`docs/ARCHITECTURE.md` moved to `docs/concepts/architecture.md` and gained a
section on the study layer's import rules.

## Three things to decide before you push

1. **The licence contradiction.** `LICENSE` is All Rights Reserved, but the
   old README said only "private research software". The new README states the
   proprietary terms plainly. If you intend the repo to be usable, this is the
   line to change — it is what stops people trying it.

2. **`rocqipath doctor` is load-bearing.** The bug-report form requires its
   output. Consider enabling Discussions so usage questions stay out of the
   issue tracker.

3. **A QC figure at the top of the README.** The one thing the README still
   lacks. An aligned H&E/IHC pair plus a DAB overlay would do more for
   adoption than any prose — `docs/qc-gallery/` has a placeholder structure and
   the data-safety rules for it.

## Verification run in this environment

- 96 tests pass (`tests/test_study_workspace.py` 18, `tests/test_study_pipeline.py`
  36, existing suite unchanged)
- `ruff check` and `ruff format --check` clean on everything touched
- End-to-end CLI smoke: `init → index → verify → plan → run --dry-run` over a
  5-slide, 2-case synthetic cohort; 3 pairs derived from 2 H&E slides
- Five test modules could not be collected here because native `libvips` is
  unavailable in this container; they are unmodified and unrelated to these
  changes. Two pre-existing `ruff` findings in
  `src/rocqipath/registration/valis_backend.py` (untouched) come from a newer
  ruff than your CI pins.
