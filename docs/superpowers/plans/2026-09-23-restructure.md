# RocqiPath 2.0 restructure — implementation plan

**Spec:** `docs/superpowers/specs/2026-09-23-restructure-design.md`
**Goal:** a simpler, better-documented package with one call shape per workflow,
one registry behind Python, the CLI, and Studio, and chaining through run
manifests. No capability is lost.
**Constraints:**
- Python 3.10–3.11.
- `import rocqipath` needs no dependencies.
- Numerical behavior is unchanged, as enforced by the golden tests.
- Docstrings stay in the code as the documentation source.
- Clean break, released as 2.0.

**Delivery:** one PR per phase, merged in order. Each phase must leave
`python -m pytest`, `ruff check src tests`, and the CLI smoke checks green.

**Rules for every phase:**
- Use `git mv` for moves so history follows files.
- Update imports, tests, and notebooks in the same commit as the move.
- Never change behavior and location in the same commit.

---

## Phase 0 — Safety net (golden baseline)

Nothing in the package is moved in this phase. It adds the tests that prove
later phases lose nothing.

- [ ] **Golden tests.** Add `tests/golden/test_golden_workflows.py`. Each
  scanner-free workflow runs on `tests/fixtures/synthetic.py` data through the
  **current** API:
  - tissue extraction (Otsu), TMA extraction, paired patch extraction plus reconstruction;
  - ORB alignment, when pyvips/openslide are available (otherwise skipped, as today);
  - Reinhard stain train/apply (Macenko and Vahadane when TIAToolbox is present);
  - cell counting in single, batch, and paired modes;
  - IHC overlay, grid map, and comparison figure.
- [ ] **Recorded values.** For each run, record the following in
  `tests/golden/expected/<workflow>.json`:
  - the sorted relative output file tree;
  - region counts and boxes;
  - cell counts;
  - image shapes, plus checksums of the normalized and reconstructed pixels;
  - manifest keys.

  `--update-golden` regenerates these files, but only in Phase 0.
- [ ] **Adapter.** Put a thin `tests/golden/_calls.py` adapter between the
  golden tests and the API. It is the **only** file later phases edit to follow
  API changes. The expected JSON must not change.
- [ ] **Structure test.** Add `tests/test_structure.py` (`xfail` for now). It
  covers no duplicate module basenames and no helper defined twice
  (`tissue_fraction`, `list_wsi_files`).
- [ ] **Verify.** The golden suite passes on 3.10 and 3.11 in CI. Commit the
  expected files.

## Phase 1 — Layout: pure moves, no behavior change

The target tree is spec §3. The old-to-new module moves are:

| From | To |
|---|---|
| `core/slide.py`, `core/magnification.py`, `core/output.py` | `io/slide.py`, `io/magnification.py`, `io/output.py` |
| `utils/imageio.py`, `utils/vips.py`, `utils/discovery.py`, `utils/naming.py`, `utils/manifest.py` | `io/images.py`, `io/vips.py`, `io/discovery.py`, `io/naming.py`, `io/manifest.py` |
| `core/tissue.py` | `tissue/masks.py` |
| `extraction/detection.py`, `extraction/semantic.py` | `tissue/detection.py`, `tissue/semantic.py` |
| `extraction/tissue.py` | `extraction/regions.py` |
| `extraction/patch_pipeline.py` | `extraction/patches.py` |
| `extraction/patches.py` | `extraction/patch_single.py` |
| `extraction/reconstruction.py` | `extraction/reconstruct.py` |
| `registration/*` | `alignment/*` |
| `registration/orb_backend.py`, `orb_stages.py` | `alignment/orb/backend.py`, `alignment/orb/stages.py` |
| `registration/valis_backend.py` | `alignment/valis.py` |
| `registration/patches.py` | `alignment/grid_patches.py` |
| `analysis/counting.py`, `analysis/reporting.py` | `counting/counter.py`, `counting/report.py` |
| `visualization/*` | `viz/*` |
| `visualization/comparison_workflow.py` | `viz/comparison.py` |
| `visualization/overlays.py`, `overlay_masks.py`, `overlay_figures.py` | `viz/overlays/workflow.py`, `masks.py`, `figures.py` |
| `visualization/figure_helpers.py` | `viz/_figure_helpers.py` |
| `core/exceptions.py` | `errors.py` |
| `core/console.py`, `core/logging.py`, `utils/validation.py`, `utils/geometry.py`, `utils/reporting.py` | `_internal/*` |
| `config/base.py` | `_internal/config.py` |
| `config/extraction.py`, `config/registration.py`, `config/stain.py`, `config/analysis.py`, `config/visualization.py` | `extraction/config.py`, `alignment/config.py`, `stain/config.py`, `counting/config.py`, `viz/config.py` |

Steps:

- [ ] **Moves.** Do the moves in 4 commits (io+tissue, extraction+alignment,
  stain+counting+viz, internal+config+errors). Remove the empty `core/`,
  `utils/`, `config/`, `analysis/`, `registration/`, and `visualization/` packages.
- [ ] **Deduplicate helpers.**
  - `tissue_fraction` gets one definition in `tissue/masks.py`. The copies in
    `stain/normalizers.py` and `utils/geometry.py` import it. First check that
    their semantics are identical; if they differ, keep separately named
    functions rather than merge them.
  - `list_wsi_files` gets one definition in `io/discovery.py`, and
    `alignment/pipeline.py` imports it.
- [ ] **Update imports** across `src`, `tests`, and `how_to_use/*.ipynb`. Reorganize
  `tests/` to mirror the package (`tests/io/`, `tests/extraction/`, ...).
- [ ] **Remove `xfail`** from `tests/test_structure.py`.
- [ ] **Verify.** The golden tests pass. Only `_calls.py` import lines change.
  Ruff and the import-isolation test pass.

## Phase 2 — Public API, registry, config simplification

- [ ] **Registry.** Add `rocqipath/workflows.py`:
  - `Item`, `Result`, `InputSpec`, and the `Workflow` record;
  - the `@workflow(name, config, extra, inputs)` decorator;
  - `WORKFLOWS`, `run()`, and `list_workflows()`.

  The decorator:
  - builds the config from `config` plus `**overrides`, including `a__b` for
    nested fields;
  - rejects unknown keys and suggests the closest field name with `difflib`;
  - creates `output_dir` and returns a `Result`.

  The run manifest is added in Phase 3. Until then `Result.manifest_path` is `None`.
- [ ] **Config helpers.** Extend `_internal/config.py` with:
  - `BaseConfig.replace()`, `to_dict()`/`from_dict()` (nested), and TOML loading;
  - a numpy `Parameters` parser that caches per-field help;
  - `field_schema(cfg_cls)`, returning type, default, choices, advanced, and help.
- [ ] **Rename configs and remove path fields.**
  - `ExtractTissueConfig`, `ExtractTMAConfig`, `ExtractPatchesConfig`,
    `StainConfig`, `CountCellsConfig`, `OverlayConfig`, and a new
    `CompareConfig` (built from `visualize_side_by_side` keyword arguments).
  - Remove `input_dir`, `output_dir`, `base_output_dir`, `he_dir`, and
    `aligned_dir` from every config.
- [ ] **Split `AlignmentConfig`.** It becomes `AlignConfig`, with nested `orb:
  OrbOptions` and `valis: ValisOptions`. Move each field's existing docstring
  text with it. Add `tests/alignment/test_config_mapping.py`, asserting that
  every old field maps to exactly one new location and keeps its default.
- [ ] **Typed `WSIRegistrar`.** `WSIRegistrar` and `ReversiblePatchExtractor`
  take typed configs instead of dicts.
- [ ] **Wrap the workflows** with `@workflow` in their packages. Keep the
  existing function bodies and delegate to them:

  | Workflow | Delegates to |
  |---|---|
  | `extract_tissue` | `run_tissue_pipeline` body |
  | `extract_tma` | `run_tma_extraction_pipeline` body |
  | `extract_patches` | `run_patch_extraction` body |
  | `align` | `AlignmentProcessor` |
  | `train_stain_normalizer` | `run_stain_normalization_train` body |
  | `normalize_stain` | `run_stain_normalization_apply` body; `normalizer=` accepts a weights path, a `Result`, or a normalizer object |
  | `count_cells` | `count_slide` for one input, `count_batch` for many, `count_slide_pair` when `compare_to=` is given |
  | `compare` | `visualize_side_by_side` |
  | `overlay_markers` | `process_ihc_overlay` |

  Each workflow returns `list[Item]` plus a summary.
- [ ] **Remove the old entry points.** Delete `run_*` and `process_*`, or make
  them private, since this is a clean break. Tier-2 building blocks keep their
  names.
- [ ] **Tier-1 `__init__.py`.** Add lazy `__getattr__` and an exact `__all__`
  (spec §3.1). Add `open_slide()` to `io/slide.py`.
- [ ] **Tests.**
  - Rewrite `tests/test_public_api.py` for the Tier-1 and Tier-2 surface.
  - Point `tests/golden/_calls.py` at the new API.
  - Add a registry contract test: docstring present, every config field
    documented, and the extra present in pyproject.
- [ ] **Docstrings.** Every Tier-1 function gets full numpy docstrings with
  Parameters, Returns, Raises, and Examples. Existing config docstrings are
  kept and extended so every field is covered.
- [ ] **Verify.** Golden tests are unchanged, and the contract and
  import-isolation tests pass.

## Phase 3 — Run manifest and chaining

- [ ] **Run manifest.** In `io/manifest.py`, add `write_run_manifest(result)` and
  `read_run_manifest(folder)` for schema v1 (spec §5). Paths are relative to the
  manifest, and reading validates the schema version.
- [ ] **Decorator.** The decorator writes `rocqipath.json` after every
  successful run. A failed run writes nothing, so a partial folder is never
  mistaken for a valid input.
- [ ] **Input resolver.** Add `io/inputs.py` with
  `resolve_inputs(inputs, spec) -> list[Item]`. It handles:
  - a file;
  - a raw folder, using existing discovery and naming patterns;
  - a list;
  - a `Result`;
  - a folder that contains a manifest, filtered by `spec.roles`.

  The error message states which roles were expected and which were found.
- [ ] **Declare inputs.** Each workflow declares its `InputSpec`.
  `extract_patches` accepts `("reference", "aligned")`, `count_cells` accepts
  slides or patches, and `normalize_stain` accepts images or patches.
- [ ] **Keep existing manifests.** Per-region, per-slide, and aligned-magnification
  manifests are unchanged, and `SlideReader` still reads the aligned manifest.
- [ ] **Chaining tests.** Add `tests/test_chaining.py`, covering:
  - `align` → `extract_patches` → `count_cells` on synthetic pairs;
  - both a `Result` and a folder path as input;
  - a moved output folder still resolving;
  - a clear error when the roles don't match.
- [ ] **Notebook 08.** Remove the staging helper.
- [ ] **Verify.** Golden tests pass. The expected file trees now also contain
  `rocqipath.json`; regenerate them with a reviewed diff that shows only that
  file added.

## Phase 4a — CLI and Studio backend from the registry

- [ ] **Generated CLI.** Rewrite `cli/`:
  - `build_parser()` iterates `WORKFLOWS`;
  - each config field becomes a flag, with help from the parsed docstring;
  - advanced flags appear only under `--help-all`;
  - `--config file.toml` is supported;
  - nested fields become `--valis.max-error-um`.

  Add `rocqipath list`, `rocqipath info SLIDE`, and `rocqipath studio`, which
  moves the launcher from `studio/__main__` behind the CLI. Delete
  `cli/commands/`.
- [ ] **CLI tests.** Update `tests/test_cli.py`: every workflow has a subcommand,
  and the help for each shows every non-advanced field. Record every flag
  rename for `MIGRATION.md`.
- [ ] **Studio backend.**
  - Delete `studio/workflows.py`.
  - Add `rocqipath/extras.py` with one extras→modules table. The Studio
    capability checks and a pyproject consistency test both use it.
  - `GET /api/workflows` returns the registry plus `field_schema` for each
    workflow, and whether its extra is installed.
  - `POST /api/jobs` accepts `{workflow, inputs: [slide_id | job_id], params}`.
    The worker calls `rp.run`. A job ID resolves to that job's output folder.
- [ ] **Studio tests.** Update `tests/test_studio.py`. The existing security
  tests stay unchanged. Add tests for the schema endpoint and for a chained
  job.
- [ ] **CI.** `ci.yml` smoke-tests `rocqipath list` and `--help` for each
  registered workflow.
- [ ] **Verify.** Golden, CLI, and Studio tests pass.

## Phase 4b — Studio frontend

- [ ] **Build the interface.** Replace the placeholder `studio-web/app/page.tsx`
  with the interface from the 2026-09-07 Studio spec:
  - a slide library (folder browser/import);
  - a zoomable viewer with a comparison pane;
  - a generic `WorkflowForm` driven by `/api/workflows`, with basic/advanced
    sections, choices as selects, and help as tooltips;
  - job history with logs, artifacts, and "use as input".
- [ ] **No per-workflow frontend code.** Add a frontend unit test that renders
  every schema returned by a fixture snapshot of `/api/workflows`.
- [ ] **Package it.** The production build is packaged under `studio/static`,
  with a `studio` extra in pyproject.
- [ ] **Verify.** Run `pnpm build`, the backend tests, and an HTTP smoke test,
  and check the page manually in a local preview.

## Phase 5 — Documentation and 2.0 release

- [ ] **Site setup.** Add a `docs` extra (`mkdocs-material`, `mkdocstrings[python]`),
  `mkdocs.yml`, and the site structure from spec §8. The reference pages are
  one-liners (`::: rocqipath.align`) so the docstrings remain the only source.
- [ ] **Hand-written pages.** Write `index.md`, `getting-started.md`,
  `concepts/*`, one short `workflows/*.md` per workflow, and
  `contributing/{architecture,adding-a-workflow,testing}.md`.
  `adding-a-workflow.md` walks through adding a toy workflow end to end and is
  checked by a doctest-style test.
- [ ] **Move existing docs.** `how_to_use/09_Studio_Web.md` → `docs/studio.md`;
  `docs/reliability-review.md` → `docs/history/`.
- [ ] **Notebooks.** Update `how_to_use/*.ipynb` to `import rocqipath as rp` and
  trim them. `tests/test_readme_examples.py` also executes the README examples.
- [ ] **README.** Rewrite it: what RocqiPath is, the install matrix, a
  five-line Python example, the CLI, Studio, and links to the docs.
- [ ] **`MIGRATION.md`.** Map every old import, function, config class, config
  field, and CLI flag to its replacement, using the phase notes.
- [ ] **pyproject.** Set `version = "2.0.0"` and `requires-python = ">=3.10,<3.12"`.
- [ ] **CI.** Add `mkdocs build --strict`.
- [ ] **Final review.** Run the full suite on 3.10 and 3.11, build the wheel,
  install it without extras (import plus `rocqipath list`), and review the
  complete diff against spec §1 point by point.

---

## Done criteria

- [ ] Every row of spec §4.1 has a working new entry point, covered by golden or unit tests.
- [ ] `import rocqipath as rp; dir(rp)` shows the full Tier-1 surface with no extras installed.
- [ ] Python, the CLI, and Studio all list the same workflows from `WORKFLOWS`.
- [ ] `align` → `extract_patches` → `count_cells` chains with no staging code.
- [ ] Adding a workflow means writing one function with a docstring and a config, with no CLI or Studio edits. The contributing guide demonstrates this.
- [ ] The docs site builds strictly from docstrings plus the concept and workflow pages.
