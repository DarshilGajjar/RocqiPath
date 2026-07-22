# Changelog

All notable changes to RocqiPath will be documented in this file from the
1.0.0 maintenance baseline forward.

## [Unreleased]

No unreleased changes yet.

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
- Made registration dry runs return discovered case results.

### Verification

- Added scanner-free synthetic fixtures covering registration discovery,
  paired extraction, manifests, patch pairing, ORB streaming, and tissue masks.
- Added a Python 3.10/3.11 CI matrix with editable-install, metadata, wheel,
  compilation, test, lint, and formatting checks.
