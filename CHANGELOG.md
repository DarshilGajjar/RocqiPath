# Changelog

All notable changes to RocqiPath will be documented in this file from the
1.0.0 maintenance baseline forward.

## [Unreleased]

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
- Added `docs/ARCHITECTURE.md` with dependency-direction and placement rules.

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

| Old import or module | New canonical location | Compatibility |
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

## [1.0.0] - 2026-07-22

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
