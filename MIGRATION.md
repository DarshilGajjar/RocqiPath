# Migrating to RocqiPath 2.0

RocqiPath 2.0 reorganizes the package around one calling convention. Every
capability of 1.x is still available. This page maps each old name to its
new one.

**The short version:**

```python
import rocqipath as rp

rp.<workflow>(inputs, output_dir, *, config=None, **settings)  # returns a Result
```

- **Paths are arguments.** Input and output folders are never config fields
  any more.
- **Configs are named after their workflow** and live next to it
  (`rp.AlignConfig`, `rp.CountCellsConfig`, …).
- **The command line** has one command per workflow. Run `rocqipath list`.

## Workflows

| 1.x | 2.0 |
|---|---|
| `run_tissue_pipeline(in_dir, out_dir, TissueExtractionConfig(...))` | `rp.extract_tissue(in_dir, out_dir, **settings)` |
| `extract_tissue_regions(slide, out, cfg)` | unchanged, now `rocqipath.extraction.extract_tissue_regions` |
| `run_tma_extraction_pipeline(in_dir, out, cfg, target_stains=[...])` | `rp.extract_tma(in_dir, out, stains=[...])` |
| `run_patch_extraction(PatchExtractionConfig(he_dir=, aligned_dir=, output_dir=, ...))` | `rp.extract_patches(aligned, out, reference=he_dir)`, or simply `rp.extract_patches(rp.align(...), out)` |
| `run_alignment(AlignmentConfig(input_dir=, output_dir=, ...))` | `rp.align(input_dir, output_dir, **settings)` |
| `WSIRegistrar(ref, mov, {"base_output_dir": ...}, valis_cfg=)` | `rp.alignment.WSIRegistrar(ref, mov, AlignConfig(...), output_dir=...)` (a settings dict still works) |
| `run_stain_normalization_train(in_dir, out, StainNormalizationConfig(n_type=...))` | `rp.train_stain_normalizer(in_dir, out, method=...)` |
| `run_stain_normalization_apply(in_dir, out, cfg)` with `weights_path` | `rp.normalize_stain(in_dir, out, normalizer=weights_file_or_result)` |
| `PositiveCellCounter(CellCountingConfig(output_dir=...)).count_slide(p, label=)` | `rp.count_cells(p, out, label=...)` |
| `…count_batch(folder)` | `rp.count_cells(folder, out)` |
| `…count_slide_pair(gt, pred, save_plots=, max_plots=, dpi=)` | `rp.count_cells(gt, out, compare_to=pred, save_plots=, max_plots=, dpi=)` |
| `visualize_side_by_side(he, gt, pred, save_path, dpi, title_he, …)` | `rp.compare([he, gt, pred], out_dir, dpi=, title_reference=, …)` |
| `process_ihc_overlay(data_in, IHCOverlayConfig(save_dir=...))` | `rp.overlay_markers(data_in, out_dir, markers=, combinations=, base_marker=)` |
| `plot_selector_map`, `view_pairs`, `export_wsi_thumbnails`, grid-map exports | unchanged names in `rocqipath.viz` |
| `ReversiblePatchExtractor`, normalizer classes, `get_normalizer` | unchanged, in `rocqipath.extraction` / `rocqipath.stain` |
| `SlideReader(path)` | `rp.open_slide(path, target_magnification=, source_magnification=)`, or `rocqipath.io.SlideReader` |

Workflows now return a `Result`. The values the old functions returned are
in `result.summary`: `summary["regions"]`, `summary["cases"]`, `summary["results"]`,
and so on. Every produced file is listed in `result.items`.

## Configs

| 1.x | 2.0 |
|---|---|
| `TissueExtractionConfig` | `ExtractTissueConfig` |
| `TMAExtractionConfig` | `ExtractTMAConfig` (new field `stains`, formerly `target_stains=`) |
| `PatchExtractionConfig` | `ExtractPatchesConfig`: `he_dir` → `reference=`, `aligned_dir` → `inputs`, `output_dir` → argument; `biomarker_folders` now defaults to every subfolder |
| `AlignmentConfig` | `AlignConfig` (see below) |
| `ValisConfig` | `ValisOptions`, the `valis` field of `AlignConfig` |
| `OrbConfig` | `OrbOptions`, the `orb` field of `AlignConfig` |
| `StainNormalizationConfig` | `StainConfig`: `n_type` → `method`; `weights_path` removed (weights are written to the output folder; pass `normalizer=` to apply) |
| `CellCountingConfig` | `CountCellsConfig`: `output_dir` → argument; new `label`, `save_plots`, `max_plots`, `dpi` |
| `IHCOverlayConfig` | `OverlayConfig`: `save_dir` → argument |
| — | `CompareConfig` (the keyword arguments of `visualize_side_by_side`) |
| `BaseExtractionConfig` | private (`_RegionExtractionConfig`) |

### `AlignmentConfig` → `AlignConfig`

| 1.x field | 2.0 |
|---|---|
| `input_dir`, `output_dir` | arguments of `rp.align` |
| `alignment_method` | `backend` |
| `valis_config` | `valis` |
| `valis_max_error_um` | `valis.max_acceptable_error_um` |
| `valis_non_rigid_dim` | `valis.max_non_rigid_reg_dim_px` |
| `valis_feature_detector` | `valis.feature_detector` |
| `valis_num_features` | `valis.num_features` |
| `valis_check_reflections` | `valis.check_for_reflections` |
| `valis_norm_method` | `valis.norm_method` |
| `keep_valis_diagnostics` | `valis.keep_diagnostics` |
| everything else | unchanged |

Nested fields can be set with a double underscore:
`rp.align(..., valis__num_features=3000)`.

!!! note "ORB settings now take effect"
    In 1.x, `OrbConfig` was never passed to the ORB backend, which always
    used its built-in values. `OrbOptions` is wired to the backend and its
    defaults are those built-in values, so results are unchanged. Its field
    names drop the `orb_` prefix (`orb_thumb_size` → `thumb_size`), and the
    effective `ransac_threshold` default is `20.0`; the 1.x class said `5.0`
    but that value was never applied.

## Modules

| 1.x | 2.0 |
|---|---|
| `rocqipath.config.*` | `rocqipath.<package>.config`, and every config from `rocqipath` |
| `rocqipath.core.SlideReader`, `.magnification`, `.output` | `rocqipath.io` |
| `rocqipath.core.tissue` | `rocqipath.tissue` (`rocqipath.tissue.masks`) |
| `rocqipath.core.exceptions` | `rocqipath.errors` (also `rp.RocqiPathError`, …) |
| `rocqipath.core.console`, `.logging` | private (`rocqipath._internal`); use `rp.set_log_level` |
| `rocqipath.utils.discovery`, `.naming`, `.imageio`, `.vips`, `.manifest` | `rocqipath.io.discovery`, `.naming`, `.images`, `.vips`, `.manifest` |
| `rocqipath.utils.geometry`, `.validation`, `.reporting` | private (`rocqipath._internal`) |
| `rocqipath.registration` | `rocqipath.alignment` (`valis_backend` → `valis`, `patches` → `grid_patches`) |
| `rocqipath.analysis` | `rocqipath.counting` (`counting` → `counter`, `reporting` → `report`) |
| `rocqipath.visualization` | `rocqipath.viz` (`comparison_workflow` → `comparison`) |
| `rocqipath.extraction.tissue` | `rocqipath.extraction.regions` |
| `rocqipath.extraction.patch_pipeline` | `rocqipath.extraction.patches` |
| `rocqipath.extraction.patches` (single-slide helper) | `rocqipath.extraction.patch_single` |
| `rocqipath.extraction.reconstruction` | `rocqipath.extraction.reconstruct` |
| `rocqipath.extraction.detection`, `.semantic` | `rocqipath.tissue.detection`, `.semantic` |
| `rocqipath.stain.pipeline` | `rocqipath.stain.batch` |
| `WSIProcessingError` | `RocqiPathError` |

Duplicated helpers with different meanings now have distinct names:
`rocqipath.stain.normalizers.tissue_fraction` is private, and
`rocqipath.utils.geometry.tissue_fraction` is `region_tissue_fraction`. The
single public `tissue_fraction` is in `rocqipath.tissue`.

## Command line

| 1.x | 2.0 |
|---|---|
| `rocqipath extract IN OUT` | `rocqipath extract-tissue IN OUT` |
| `rocqipath extract IN OUT --mode tma` | `rocqipath extract-tma IN OUT` |
| `extract --target-stains A B` | `extract-tma --stains A B` |
| `extract --all-shapes` | `extract-tma --no-only-circles` |
| `extract --shared-detection` | `extract-tma --no-per-stain-detection` |
| `extract --no-fallback-to-reference` | `extract-tma --no-fallback-to-he` |
| `extract --semantic-weights F` | `--semantic-weights-path F` |
| `extract --overwrite` | `--no-skip-existing` |
| `rocqipath align IN OUT --method orb` | `rocqipath align IN OUT --backend orb` |
| `align --valis-max-error-um X` | `align --valis.max-acceptable-error-um X` |
| `align --qc` | `align --qc-enabled` |
| `rocqipath stain --mode train -i DIR -o OUT --n-type macenko` | `rocqipath train-stain-normalizer DIR OUT --method macenko` |
| `rocqipath stain --mode apply -i DIR -o OUT -w W` | `rocqipath normalize-stain DIR OUT --normalizer W` |
| `stain -s he,ihc` | `--stains he ihc` |
| `rocqipath count IN -o OUT` | `rocqipath count-cells IN OUT` |
| `count --pred P` | `count-cells --compare-to P` |
| `count --no-plots` | `count-cells --no-save-plots` |
| `rocqipath compare --he H --gt-ihc G --pred-ihc P --output F` | `rocqipath compare H G P OUT_DIR [--figure-name F]` |
| `compare --manifest M` | `rocqipath compare M OUT_DIR` |
| `compare --title-he/--title-gt/--title-pred` | `--title-reference/--title-truth/--title-prediction` |
| `python -m rocqipath.studio` | `rocqipath studio` (the module still works) |

Other flags keep their names. Every command has `--help`, `--help-all`
and `--config settings.toml`.

## Studio

The job API accepts `{"workflow", "inputs": [{"kind", "id"}], "options",
"settings"}`, and workflow names are the registry names (`count_cells`,
`extract_tissue`, …). `GET /api/workflows` describes every workflow's
settings.

## Output files

- **New run manifest:** every workflow's output folder also gets a
  `rocqipath.json` recording the run.
- **TMA core manifests** record the new `stains` setting.
- **Unchanged:** all other file names and layouts, as verified by the
  golden snapshot tests.
