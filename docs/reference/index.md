# `rocqipath`

Everything most users need is available from `import rocqipath as rp`. It is
imported lazily, so `import rocqipath` works with no extras installed.

| Kind | Names |
|---|---|
| Workflows | [`extract_tissue`](../workflows/extract-tissue.md), [`extract_tma`](../workflows/extract-tma.md), [`extract_patches`](../workflows/extract-patches.md), [`align`](../workflows/align.md), [`train_stain_normalizer`, `normalize_stain`](../workflows/stain.md), [`count_cells`](../workflows/count-cells.md), [`compare`](../workflows/compare.md), [`overlay_markers`](../workflows/overlay-markers.md) |
| Running | [`run`, `list_workflows`, `Result`, `Item`](results.md) |
| Slides | [`open_slide`](io.md) |
| Configs | [all config classes](configs.md) |
| Errors | [`RocqiPathError` and subclasses](errors.md) |
| Logging | `set_log_level("DEBUG")` |

Packages below the top level are building blocks for advanced use:
`rocqipath.io`, `rocqipath.tissue`, `rocqipath.extraction`,
`rocqipath.alignment`, `rocqipath.stain`, `rocqipath.counting` and
`rocqipath.viz`. Anything under `rocqipath._internal` is private.

::: rocqipath._internal.logging.set_log_level
    options:
      show_root_heading: true
