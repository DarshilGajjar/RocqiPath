# RocqiPath 2.0 restructure — design

**Status:** approved in brainstorming, 2026-09-23; implemented (see the plan's status note for deviations).
**Goal:** make RocqiPath simple to learn, use, and extend, without losing any
existing capability or the ability to add workflows later.
**Audience:** Python/notebook users, Studio (web UI) users, and contributors.
**Compatibility:** clean break, released as 2.0. `MIGRATION.md` maps every old
import, function, config, and CLI flag to its replacement.

## 1. Problems this solves

| Problem today | Consequence |
|---|---|
| Each workflow has a different entry-point shape (`run_tissue_pipeline(in, out, cfg)`, `run_patch_extraction(cfg)`, `run_alignment(cfg)` with paths inside the config, `PositiveCellCounter(cfg).count_slide(...)`, `process_ihc_overlay(...)`, `WSIRegistrar(ref, mov, dict)`). | Users can't transfer knowledge from one workflow to the next. |
| Configs are both in `rocqipath.config` and re-exported by feature packages. `import rocqipath` exposes only `__version__`. | There are two import paths for everything, and nothing is discoverable from the top level. |
| Module names repeat with different meanings (`tissue.py` ×2, `patches.py` ×2, `reporting.py` ×2, `pipeline.py` ×2). Helpers are duplicated (`tissue_fraction` ×3, `list_wsi_files` ×2). The `core`/`utils` boundary is unclear, and `core` exports about 60 names, including console printing. | Contributors can't tell where code belongs or which copy is canonical. |
| `AlignmentConfig` has 30 fields and `ValisConfig` has 27, in a single 1,851-line file. | The alignment API is intimidating. Shared and backend-specific options are mixed together. |
| Alignment output does not match the patch extractor's input contract. Notebook 08 needs a staging helper that copies files. | Workflows don't compose. |
| The same five workflows are wired three times: the CLI (`cli/commands/*`), Studio (`studio/workflows.py`, which calls the private `_write_aligned_wsi_manifest`), and Python. | Adding or changing a workflow means editing three places, and they drift apart. |

## 2. Principles

1. **One way to call any workflow.** Every workflow is called as
   `rp.<verb>(inputs, output_dir, *, config=None, **overrides) -> Result`.
2. **Three visibility tiers.**
   - *Tier 1:* `rocqipath` itself. It contains workflows, configs, `open_slide`,
     `Result`, and errors. This is enough for most users.
   - *Tier 2:* `rocqipath.<package>`. It holds documented building blocks for
     advanced use, such as `WSIRegistrar`, normalizer classes, tissue masks,
     and `ReversiblePatchExtractor`.
   - *Private:* anything prefixed with `_` or under `rocqipath._internal`.
     No stability promise.
3. **One definition per workflow.** The registry drives the Python API, the CLI,
   and Studio.
4. **Docstrings are the documentation source of truth.** Numpy-style docstrings
   stay in the code and keep their current depth. The docs site renders them,
   and CLI help and Studio tooltips are derived from them. Nothing is written twice.
5. **Every output folder describes itself.** A `rocqipath.json` run manifest
   makes any output folder a valid input to the next workflow.
6. **Names say what the code does.** No two modules share a filename, and
   every helper has exactly one definition.
7. **Import stays dependency-free.** `import rocqipath` must work with no extras
   installed. Heavy backends load lazily inside workflows, as they do today.

## 3. Package layout

```
src/rocqipath/
  __init__.py        Tier-1 public API (lazy attribute loading, see §3.1)
  registry.py        Workflow registry, @workflow decorator, rp.run(), Result, Item
  errors.py          Public exception hierarchy (was core/exceptions.py)
  io/                Reading and writing slides and files
    slide.py           SlideReader, open_slide
    magnification.py   MagnificationPlan, build_magnification_plan, objective lookup
    images.py          imread_rgb, imwrite_rgb, save_tif, save_preview
    vips.py            libvips helpers
    discovery.py       WSI detection, listing, pair discovery (single list_wsi_files)
    naming.py          natural_sort_key, filename patterns, sample-id parsing
    output.py          OutputLayout, safe_name
    manifest.py        region/slide manifests + run manifest (rocqipath.json)
    inputs.py          resolve_inputs(): file | folder | list | Result | manifest folder
  tissue/            Tissue detection primitives (used by extraction, counting, stain)
    masks.py           tissue_mask, tissue_fraction (single definition), is_tissue, OD helpers
    detection.py       Otsu region detection
    semantic.py        TIAToolbox semantic masks/regions
  extraction/
    config.py          ExtractTissueConfig, ExtractTMAConfig, ExtractPatchesConfig
    regions.py         extract_tissue workflow
    tma.py             extract_tma workflow
    patches.py         extract_patches workflow (paired patches)
    patch_single.py    single-slide grid patch helper
    engine.py          shared region-extraction engine
    reversible.py      ReversiblePatchExtractor (Tier 2)
    reconstruct.py     patch reconstruction and pyramid export
  alignment/
    config.py          AlignConfig, OrbOptions, ValisOptions
    pipeline.py        align workflow
    registrar.py       WSIRegistrar (Tier 2; takes AlignConfig, not a dict)
    orb_backend.py, orb_stages.py
    valis.py
    export.py          aligned WSI export + aligned manifest
    quality.py         QC figures
    grid_patches.py    registrar grid-map / patch-pair methods (was registration/patches.py)
    models.py          CaseContext, AlignedCaseResult
  stain/
    config.py          StainConfig
    normalizers.py     Reinhard/Macenko/Vahadane, get_normalizer (Tier 2)
    batch.py           train_stain_normalizer, normalize_stain workflows
  counting/
    config.py          CountCellsConfig
    counter.py         PositiveCellCounter (Tier 2) + count_cells workflow
    report.py          Excel/plot reporting (was analysis/reporting.py)
  viz/
    config.py          OverlayConfig, MarkerProfile, OverlayCombo, CompareConfig
    comparison.py      compare workflow (was comparison_workflow.py)
    overlays.py        overlay_markers workflow (+ overlay_masks.py, overlay_figures.py)
    grids.py, pairs.py, thumbnails.py, roi.py, figure_helpers.py   (Tier 2 plotting helpers)
  _internal/
    base_config.py     BaseConfig, field metadata helpers, docstring → field-help parser
    console.py, logging.py, validation.py, geometry.py, config_panel.py
  cli/               Generated from the registry (see §6)
  studio/            Uses the registry (see §7)
```

The configs move next to their workflows, so a contributor finds everything
about a workflow in one folder. Tier 1 re-exports them. `config.py` is the one
filename repeated on purpose, as a per-package convention; every other module
name is unique (enforced by `tests/test_structure.py`). The duplicated helpers
had different semantics, so they were renamed rather than merged:
`tissue.masks.tissue_fraction` is the shared primitive, the stain OD preset is
private, and the bounding-box variant is `_internal.geometry.region_tissue_fraction`.

Subpackages are named with nouns (`extraction`, `alignment`, `counting`) and
workflows with verbs (`rp.align`, `rp.count_cells`). This keeps a Tier-1
function from shadowing a subpackage: `rp.align` is the function, and
`rp.alignment` is the package.

### 3.1 Tier-1 surface (`import rocqipath as rp`)

| Kind | Names |
|---|---|
| Workflows | `extract_tissue`, `extract_tma`, `extract_patches`, `align`, `train_stain_normalizer`, `normalize_stain`, `count_cells`, `compare`, `overlay_markers` |
| Generic | `run(name, inputs, output_dir, **params)`, `list_workflows()` |
| Slides | `open_slide(path, *, source_magnification=None) -> SlideReader` |
| Results | `Result`, `Item` |
| Configs | `ExtractTissueConfig`, `ExtractTMAConfig`, `ExtractPatchesConfig`, `AlignConfig`, `OrbOptions`, `ValisOptions`, `StainConfig`, `CountCellsConfig`, `CompareConfig`, `OverlayConfig`, `MarkerProfile`, `OverlayCombo` |
| Errors | `RocqiPathError` (was `WSIProcessingError`) and its existing subclasses |
| Meta | `__version__`, `set_log_level` |

`__init__.py` uses module-level `__getattr__` for lazy loading. This keeps
`import rocqipath` free of dependencies while making the full surface
discoverable through `dir(rp)` and IDE completion via `__all__`.

## 4. Workflow contract

```python
@workflow(name="align", config=AlignConfig, extra="orb", inputs=InputSpec(roles=("reference", "moving")))
def align(inputs, output_dir, *, config: AlignConfig) -> list[Item]:
    """<full numpy docstring: summary, Parameters, Returns, Raises, Examples>"""
```

The `@workflow` decorator provides these behaviors to every workflow:

1. **Configuration:** it accepts `config=None` and `**overrides`, builds the
   config (`config.replace(**overrides)`), and raises `ConfigurationError` for
   unknown keys, suggesting the closest field name.
2. **Inputs:** it resolves `inputs` through `io.inputs.resolve_inputs` (see §5).
3. **Output folder:** it creates `output_dir` and writes the run manifest
   (`rocqipath.json`) from the returned items.
4. **Return value:** it returns a `Result`.
5. **Registration:** it adds the workflow to `WORKFLOWS`, which the CLI and Studio read.

```python
@dataclass(frozen=True)
class Item:
    sample_id: str
    role: str                # "region", "core", "reference", "aligned", "patch", "normalized", "count", "figure", ...
    path: Path
    magnification: float | None = None
    source: Path | None = None      # the input this item came from
    meta: dict = field(default_factory=dict)

@dataclass(frozen=True)
class Result:
    workflow: str
    output_dir: Path
    items: tuple[Item, ...]
    summary: dict            # workflow-specific numbers (region counts, cell counts, QC metrics)
    manifest_path: Path
    def by_role(self, role) -> list[Item]: ...
    def __iter__(self): ...
```

**Paths are never config fields.** `input_dir`, `output_dir`, and
`base_output_dir` leave every config.

### 4.1 Mapping of capabilities to the new API

No capability is dropped. Every old entry point maps to a new one:

| Old | New |
|---|---|
| `extraction.run_tissue_pipeline`, `extract_tissue_regions` | `rp.extract_tissue` (the single-slide function stays Tier 2 as `rp.extraction.extract_tissue_regions`) |
| `extraction.run_tma_extraction_pipeline` and its helpers | `rp.extract_tma`; helpers stay in `rp.extraction.tma` |
| `extraction.run_patch_extraction` | `rp.extract_patches` |
| `extraction.ReversiblePatchExtractor` | `rp.extraction.ReversiblePatchExtractor` |
| `registration.run_alignment`, `AlignmentProcessor` | `rp.align` |
| `registration.WSIRegistrar(ref, mov, dict)` | `rp.alignment.WSIRegistrar(ref, mov, AlignConfig)` |
| `stain.run_stain_normalization_train` / `_apply` | `rp.train_stain_normalizer` / `rp.normalize_stain` |
| `stain.get_normalizer`, normalizer classes | `rp.stain.*` (unchanged) |
| `analysis.PositiveCellCounter.count_slide` / `count_batch` / `count_slide_pair` | `rp.count_cells(inputs, out)` (one slide or many, resolved) and `rp.count_cells(inputs, out, compare_to=pred)` (paired); the class stays Tier 2 |
| `visualization.comparison_workflow.visualize_side_by_side` | `rp.compare` |
| `visualization.process_ihc_overlay` | `rp.overlay_markers` |
| `visualization.plot_selector_map`, `view_pairs`, `visualize_patch_pairs`, `export_wsi_thumbnails`, grid-map exports | `rp.viz.*` (unchanged names) |
| `core.SlideReader` | `rp.open_slide(...)` / `rp.io.SlideReader` |
| `core.tissue.*` | `rp.tissue.*` |
| `core` console/logging | `rp._internal` (logging level via `rp.set_log_level`, which is kept public) |

### 4.2 Config simplification

- **Naming:** each config is named after its verb: `ExtractTissueConfig`,
  `ExtractTMAConfig`, `ExtractPatchesConfig`, `AlignConfig`, `StainConfig`,
  `CountCellsConfig`, `CompareConfig`, `OverlayConfig`.
- **Alignment split:** `AlignConfig` keeps only shared settings: pairing,
  magnification, export level, QC, and `backend`. Backend-specific settings
  move to `orb: OrbOptions` and `valis: ValisOptions`, which are nested
  dataclasses with defaults. Overrides reach nested fields with double
  underscores, for example `rp.align(..., valis__max_error_um=5)` and the CLI
  flag `--valis.max-error-um`.
- **Shared base:** `BaseExtractionConfig` becomes a private shared base.
- **Field metadata:** every field carries
  `metadata={"choices": ..., "advanced": bool, "studio": bool}`. Help text is
  not duplicated in metadata. `_internal.config` parses each config's numpy
  `Parameters` section once and caches the result, so the docstring remains
  the single source of truth.

## 5. Chaining: run manifest and input resolver

Every workflow writes this file at `<output_dir>/rocqipath.json`:

```json
{
  "schema": 1,
  "workflow": "align",
  "rocqipath_version": "2.0.0",
  "created": "2026-09-23T10:00:00Z",
  "config": { "...": "serialized config" },
  "inputs": ["/abs/path/pairs"],
  "items": [
    {"sample_id": "sample_0001", "role": "reference", "path": "cd8/sample_0001_he.tiff", "magnification": 20.0},
    {"sample_id": "sample_0001", "role": "aligned",   "path": "cd8/sample_0001_cd8_aligned.ome.tiff",
     "magnification": 20.0, "source": "/abs/path/pairs/cd8/moving/sample_0001_cd8.tiff"}
  ]
}
```

- Item paths are relative to the manifest, so output folders can be moved.
- The existing per-slide and per-region manifests and the aligned-WSI
  magnification manifest are kept. `SlideReader` still reads the aligned
  manifest, so that behavior does not change.

`resolve_inputs(inputs, spec)` accepts these forms:

| Input form | How it is resolved |
|---|---|
| a single file | used as is |
| a folder of raw slides | slides are discovered with the existing discovery rules and pattern matching |
| a list of paths | each path is used |
| a `Result` | its items are used |
| a folder containing `rocqipath.json` | its items are read, filtered by the roles in `InputSpec` |

`extract_patches` declares `roles=("reference", "aligned")`, so it can take
`align` output directly. This removes the staging helper in notebook 08.

## 6. CLI

The CLI is generated from the registry:

```
rocqipath list                          # workflows, required extra, installed?
rocqipath info SLIDE                    # open_slide summary: dims, levels, magnification
rocqipath <workflow> INPUTS... OUTPUT [--field value ...] [--config file.toml]
```

- **Flags:** each config field becomes one `--kebab-case` flag. Type, default,
  and choices come from the dataclass, and help text comes from the docstring.
- **Visible flags:** advanced fields appear only in `--help-all`.
- **Command names:** subcommands are the workflow names with hyphens
  (`extract-tissue`, `extract-tma`, `train-stain-normalizer`, ...). They replace
  `extract --mode`, `stain train/apply`, and `count --pred`.
- **Flag names:** existing flag names are kept wherever the field name is
  unchanged. `MIGRATION.md` lists every renamed flag.
- **Config files:** the new `--config` option loads a TOML file, so a run can be
  reproduced from its saved configuration.

## 7. Studio

- **Backend:** `studio/workflows.py` is deleted.
  - `GET /api/workflows` returns `rp.list_workflows()` with a JSON schema for
    each config (type, default, choices, advanced, help from the docstring)
    and whether its extra is installed. Installation is checked with the
    registry's `extra` and one shared `extras.py` table of the modules each
    extra needs, which pyproject is also tested against.
  - `POST /api/jobs {workflow, inputs, params}` runs `rp.run(...)` in the
    existing worker subprocess. An input can be a registered slide ID or a
    previous job ID; a previous job resolves to that job's output folder and
    manifest, which enables chaining.
- **Preserved as is:** loopback-only access, same-origin mutations, path
  containment, the SQLite store, one worker at a time, cancellation, and
  artifact downloads restricted to the job folder.
- **Frontend:** `studio-web/app/page.tsx` is currently a placeholder. The
  interface described in the 2026-09-07 Studio spec is built on the
  schema-driven model:
  - a slide library;
  - a viewer;
  - one generic `WorkflowForm` that renders any config schema, with
    basic/advanced sections;
  - a job list with logs, artifacts, and "use as input".
- **Adding a workflow in the frontend:** a new workflow needs no frontend code.

## 8. Documentation

- **Docstrings (primary):** every Tier-1 and Tier-2 object has a complete numpy
  docstring with Parameters, Returns, Raises, and Examples. The existing long
  config docstrings stay. They are extended where needed so every field
  appears in `Parameters`, which the field-help parser requires.
- **Site:** MkDocs Material with mkdocstrings (numpy style), using a new `docs`
  extra. `mkdocs build --strict` runs in CI. Structure:

```
docs/
  index.md                    what RocqiPath does, 5-line example, install matrix
  getting-started.md          install (extras + OpenSlide/libvips), first run in Python, CLI, Studio
  concepts/
    magnification.md          objective magnification vs pyramid level, source_magnification
    outputs-and-manifests.md  output layout, rocqipath.json, Result
    chaining.md               passing results between workflows
  workflows/                  one short page per workflow: purpose, minimal example, outputs, link to reference
  studio.md                   (moved from how_to_use/09_Studio_Web.md)
  reference/                  auto-generated from docstrings (Tier 1 + Tier 2)
  contributing/
    architecture.md           layout, tiers, registry, lazy imports
    adding-a-workflow.md      step-by-step with a worked example
    testing.md                synthetic fixtures, skips for optional backends
  history/reliability-review.md
  superpowers/                design specs and plans (unchanged)
```

- **Notebooks:** `how_to_use/` notebooks move to the new API. Notebook 08 drops
  its staging helper.
- **Other docs:** `README.md` is rewritten around `import rocqipath as rp`.
  `MIGRATION.md` is added at the repository root.

## 9. Testing and verification

- **Golden baseline (added before any code moves):** each workflow runs on the
  synthetic fixtures (`tests/fixtures/synthetic.py`). The test records the
  output file tree and key numbers (region counts, boxes, cell counts,
  normalized-pixel checksums) and must still pass unchanged after every phase.
  This test is the "no functionality lost" guarantee.
- **Registry contract test:** every registered workflow must have
  - a complete docstring,
  - a config whose fields all appear in its `Parameters` docstring section,
  - a CLI subcommand,
  - a Studio schema,
  - an extra listed in pyproject, and
  - a run that writes a valid `rocqipath.json`.
- **Structure tests:**
  - no duplicate module basenames;
  - `import rocqipath` works with no dependencies installed (existing import-isolation test);
  - `__all__` in Tier 1 matches §3.1 exactly.
- **Chaining tests:**
  - `align` output goes into `extract_patches`, then `count_cells`;
  - `Result` objects and folder paths both work as inputs.
- **Existing tests:** kept and updated to the new imports. `tests/` is
  reorganized to mirror the package (`tests/extraction/`, `tests/alignment/`, ...).
- **CI:** runs ruff, pytest on 3.10/3.11, CLI help for every workflow, and the
  docs build.

## 10. Out of scope and risks

- **Out of scope:** new analysis algorithms; changing numerical behavior; Python
  versions beyond 3.10–3.11. The pyproject `requires-python` bound (`<=3.15`)
  will be corrected to match the classifiers (`<3.12`).
- **Risk — alignment behavior:** alignment is the most complex area, and its
  behavior must not change when the config is split. Mitigations: golden tests
  on the ORB path; field-by-field mapping tests from old `AlignmentConfig` to
  the new `AlignConfig`, `OrbOptions`, and `ValisOptions`; VALIS tests skipped
  when it isn't installed, as today.
- **Risk — unavailable backends:** full-scale validation with real scanner
  files, VALIS, and TIAToolbox depends on locally available data and backends.
  These are verified manually by the maintainer before the 2.0 release.
