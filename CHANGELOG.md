# Changelog

All notable changes to RocqiPath will be documented in this file from the
0.0.1-beta version.

## [1.0.0] - 2026-08-04

### Added

- Added the `rocqipath.study` workspace layer: a cohort is now described once
  in `study.toml` and every stage resolves its own inputs, so no pipeline call
  needs a directory argument.
  - `study.toml` — the single hand-authored descriptor: source roots, the
    filename pattern that decodes identity, stain roles, and per-slide
    `[overrides]` for magnification fallbacks and exclusions.
  - `index.jsonl` — one record per physical slide, keyed by a `slide_uid` of
    the form `<case>__<stain>__s<NN>`. Slides are referenced in place and never
    copied or renamed.
  - Derived pairs: a pair is case × (reference stain, moving stain), so one
    H&E serves every biomarker in a cohort without being duplicated on disk.
  - `survey/` — a cheap pass recording objective magnification, microns per
    pixel, pyramid downsamples, dimensions, and vendor for every slide.
  - `rocqipath study verify` — pre-flight checks that report missing files,
    cases without a reference slide, undeclared stains, absent objective
    metadata, and slides scanned below the requested magnification, each with
    the edit that resolves it.
  - `recipe.json` — a fully resolved, hashed plan. Every artifact records the
    recipe hash it was produced under.
  - JSONL artifact manifests with sidecar metadata, written through
    `ManifestWriter` so the sidecar survives an exception mid-stage.
  - Selections: named QC views over a manifest, evaluated through a
    whitelisted AST walk rather than `eval`, saved with their rule text,
    recipe hash, and matched identifiers.
  - `ResultTable` aggregation to tidy rows, with CSV output and optional
    pandas conversion.
- Added the `Study` facade, re-exported as `rocqipath.Study`, covering
  `create`/`open`, `index`, `survey`, `verify`, `plan`, `run`, `select`,
  `selection`, `results`, and `summary`.
- Added the `rocqipath study` command group: `init`, `index`, `survey`,
  `verify`, `plan`, `run`, `select`, `results`, `show`, and `list`.
- Added `rocqipath doctor`, which reports Python, platform, native libvips and
  OpenSlide runtimes, installed extras, and the resolved workspace root. The
  bug-report template asks for its output.
- Added the `ROCQIPATH_HOME` environment variable, defaulting to
  `~/rocqipath`, as the single root for everything RocqiPath writes.
- Added an input staging layer that presents indexed slides to the existing
  directory-based pipelines using symlinks, falling back to hardlinks and then
  to copying with an explicit warning.
- Added a documentation tree under `docs/` split by intent — `start/`,
  `guides/`, `reference/`, `concepts/`, and `qc-gallery/` — with a `faq.md` and
  an error-message reference giving cause and fix for each message.
- Added `CITATION.cff` and `CITATION.md`, `SECURITY.md` including a
  patient-data policy for public issues, `CODE_OF_CONDUCT.md`, issue forms for
  bugs, slide-format problems, features, and documentation, and a pull-request
  template.

### Changed

- Rewrote `README.md` as a short entry point what RocqiPath is and is not, install with an extras table, a five-command example, and a documentation map. The detailed material moved into `docs/`.
- Moved `docs/ARCHITECTURE.md` to `docs/concepts/architecture.md`.
- Added `tomli` as a dependency on Python 3.10 only, for `study.toml` parsing;
  `tomllib` is used from Python 3.11 onward.
- Registered `study` and `doctor` in the CLI subcommand surface.

### Design notes

- Expensive stages now measure rather than decide. Study recipes default
  `patches.tissue_threshold` and `counts.tissue_threshold` to `0.0`: extraction
  and counting write every artifact with its properties, and quality filtering
  happens afterwards as a selection. Changing a threshold no longer requires
  re-extraction, rejected artifacts stay inspectable, and a methods section can
  name the exact selection and recipe hash behind a figure.
- Every existing pipeline function keeps its signature and behaviour. The study
  layer is additive; scripts and notebooks written against the pipeline API
  continue to work unchanged.

### Added

- Added canonical `TMAExtractionConfig` and
  `run_tma_extraction_pipeline` names for tissue-microarray workflows.
- Added typed `CellCountingConfig` and shared `BaseConfig.to_dict()`,
  `BaseConfig.from_dict()`, and `BaseConfig.describe()` configuration APIs.
- Added independently testable ORB registration stages and shared,
  explicitly parameterized tissue primitives.
- Added characterization coverage for every consolidated tissue path,
  discovery helper, logger configuration, and aligned-file resolver, plus
  import-isolation and executable README checks.
- Added `docs/concepts/architecture.md` with dependency-direction and placement rules.

### Changed

- Reorganized the package into the dependency layers `core` → `utils` →
  `config` → feature packages → `cli`; `core` and `utils` retain the
  base-install-only import guarantee.
- Centralized all typed workflow configurations under `rocqipath.config`
  while retaining feature-package re-exports and dict input to
  `PositiveCellCounter`.
- Consolidated duplicate discovery, logging, config reporting, aligned-file
  resolution, and tissue operations without changing their historical
  thresholds or tie-breaking behavior.
- Decomposed registration, extraction, stain normalization, cell counting,
  and visualization orchestration into responsibility-specific modules.
- Replaced the flat CLI with `align`, `extract`, `stain`, `count`, and
  `compare` subcommands while preserving the guided menu, console entry point,
  legacy underscore options, and historical `python -m` invocations.
- Standardized public and high-value API documentation on NumPy-style
  docstrings and enabled Ruff's NumPy pydocstyle rules.

### Deprecated

- Importing `rocqipath.registration.core`; import registration symbols from
  `rocqipath.registration` (or the registrar implementation from
  `rocqipath.registration.registrar`) instead.
- Constructing `CoreExtractionConfig`; use `TMAExtractionConfig` instead.
- Calling `run_core_extraction_pipeline`; use
  `run_tma_extraction_pipeline` instead.
- Accessing `rocqipath.config.DEFAULT_CONFIG`; use typed configs or
  `rocqipath.config.default_config()` instead.
- Importing `rocqipath.api`; import each helper from its owning extraction or
  visualization package instead.

All five deprecated entry points emit `DeprecationWarning`. The supported
public subpackage imports listed in the README continue to work.

### Migration guide

| Old import or module | New location | Compatibility |
|---|---|---|
| `rocqipath.magnification` | `rocqipath.core.magnification` | Old module remains a façade. |
| `rocqipath.slide` | `rocqipath.core.slide` | Old module remains a façade. |
| `rocqipath.output` | `rocqipath.core.output` | Old module remains a façade. |
| `rocqipath.exceptions` | `rocqipath.core.exceptions` | Old documented hierarchy remains supported. |
| `rocqipath.logger` | `rocqipath.core.logging` and `rocqipath.core.console` | Old module remains a façade. |
| Flat `rocqipath.utils` implementation | `rocqipath.utils.{naming,discovery,imageio,vips,geometry,manifest,validation,reporting}` | The original `rocqipath.utils` exports remain supported. |
| Flat `rocqipath.config` implementation | `rocqipath.config.{base,registration,extraction,stain,analysis,visualization}` | The import name is unchanged; configs are re-exported. |
| `rocqipath.registration.core` | `rocqipath.registration.registrar` | Old module warns and re-exports `ValisConfig` and `WSIRegistrar`. |
| `rocqipath.registration.alignment` | `rocqipath.registration.pipeline`, `.models`, and `.quality` | Old module remains a façade. |
| Registration logic formerly inside `registrar` | `rocqipath.registration.{valis_backend,orb_backend,orb_stages,export,patches}` | `WSIRegistrar` remains in `registrar`. |
| `rocqipath.extraction.core_extraction` | `rocqipath.extraction.tma` | Internal module moved; public legacy symbols warn through the subpackage façade. |
| `CoreExtractionConfig` | `TMAExtractionConfig` | Old constructor warns. |
| `run_core_extraction_pipeline` | `run_tma_extraction_pipeline` | Old function warns. |
| `rocqipath.extraction._extraction_engine` | `rocqipath.extraction.engine` and `.detection` | Old internal module remains a narrow façade. |
| `rocqipath.extraction.tissue_extraction` | `rocqipath.extraction.tissue` | Old module remains a façade. |
| `rocqipath.extraction.patch_extraction` | `rocqipath.extraction.{patches,patch_pipeline,reversible,reconstruction}` | Old module remains a façade for its public symbols. |
| `rocqipath.stain.stain_normalization` | `rocqipath.stain.normalizers` and `.pipeline` | Old module and `python -m` invocation remain façades. |
| `rocqipath.analysis.cell_counting` | `rocqipath.analysis.{counting,batch,reporting}` | Old module remains a façade. |
| `rocqipath.visualization.visualization` | `rocqipath.visualization.grids` and `.pairs` | Old module remains a façade. |
| `rocqipath.visualization.ihc_overlay` | `rocqipath.visualization.{overlays,overlay_masks,overlay_figures}` | Old module remains a façade. |
| `rocqipath.visualization.wsi_compare` | `rocqipath.visualization.{comparison,comparison_workflow,roi,figure_helpers}` | Old module and `python -m` invocation remain façades. |
| Flat `rocqipath.cli` implementation | `rocqipath.cli.commands`, `.prompts`, and `.legacy` | `rocqipath.cli:main` and the console script are unchanged. |
| Implementations in `rocqipath.api` | `rocqipath.extraction.patches` and `rocqipath.visualization.{grids,pairs,thumbnails}` | Old module warns and re-exports the moved helpers. |

## [0.0.1-beta] - 2026-07-22

### Changed

- Established `rocqipath` as the canonical distribution, import, module, and
  command namespace.
- Removed the abandoned nnU-Net-inspired planning console entry points.
- Made the static version in `pyproject.toml` authoritative and exposed it at
  runtime through installed distribution metadata, avoiding package imports
  during isolated editable builds.
- Simplified the base installation to the dependencies required by the shared
  CLI and logger.
- Kept scientific and WSI dependencies in explicit feature extras:
  `extraction`, `orb`, `valis`, `stain`, `cellcount`, and `viz`.
- Removed the temporary `wsi`, `all`, and `dev` extras. Development tools are
  installed directly by CI and are not part of the package metadata.

### Included

- Physical-magnification-aware slide reading and output planning.
- VALIS and ORB registration workflows.
- WSI tissue, TMA/core, and paired-patch extraction workflows.
- Reinhard, Macenko, and Vahadane stain normalization.
- DAB-positive cell counting and visual quality-control utilities.

### Fixed

- Repaired the grid-map API contract so WSI format detection is treated as an
  extension string and failures retain the documented three-value result.
- Made ORB aligned-WSI saving independent of VALIS and bounded-memory by
  warping disk-backed tiles into a lazy libvips pyramid.
- Corrected ORB target-to-reference save transforms, including independent
  reference and moving-slide thumbnail scales.
- Corrected cell-density tissue area to count tissue-mask pixels rather than
  the full area of every accepted tile.
- Consolidated patch discovery, aligned-target resolution, patch-pair
  discovery, and file logging behind shared helpers.
- Made registration dry runs discover and report pairs without initializing
  optional registration backends.

### Verification

- Added scanner-free synthetic fixtures covering registration discovery,
  paired extraction, manifests, patch pairing, ORB streaming, and tissue masks.
- Added a Python 3.10/3.11 CI matrix with editable-install, metadata, wheel,
  compilation, test, lint, and formatting checks.
