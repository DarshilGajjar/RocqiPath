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
- Made `src/rocqipath/__init__.py` the single source of the package version.
- Simplified the base installation to the dependencies required by the shared
  CLI and logger.
- Kept scientific and WSI dependencies in explicit feature extras:
  `extraction`, `valis`, `stain`, `cellcount`, and `viz`.
- Removed the temporary `wsi`, `all`, and `dev` extras. Development tools are
  installed directly by CI and are not part of the package metadata.

### Included

- Physical-magnification-aware slide reading and output planning.
- VALIS and ORB registration workflows.
- WSI tissue, TMA/core, and paired-patch extraction workflows.
- Reinhard, Macenko, and Vahadane stain normalization.
- DAB-positive cell counting and visual quality-control utilities.