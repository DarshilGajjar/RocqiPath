# Changelog

## 1.1.0

- Reorganized the flat script collection into a professional `src/` package.
- Separated WSI tissue extraction from TMA/core extraction while retaining
  shared extraction primitives.
- Replaced ambiguous pyramid-index settings with physical magnification; 20x
  is now the default across extraction, registration patches, and cell counts.
- Added correct 80x-to-20x TMA downsampling and independently resolved
  reference/moving slide plans.
- Added a shared OpenSlide/PIL reader and automatic magnification recovery from
  RocqiPath region manifests.
- Standardized outputs as `<root>/<module>/<individual_item>` and flattened
  region/patch channel subfolders.
- Fixed H&E alias matching, arbitrary target-stain discovery, target-stain
  selection, target-resolution MPP area calculations, resource cleanup, and
  unused imports.
- Added package exports, unit tests, CI, contributor guidance, and updated
  installation metadata.
