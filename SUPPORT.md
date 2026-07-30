# RocqiPath support policy

## Supported releases

The `1.0.x` series is the first verified maintenance line. Only the latest
patch release in that line receives fixes. RocqiPath is private research
software: support means reproducible installation, documented APIs, regression
tests, and best-effort maintenance; it does not imply clinical validation.

## Runtime matrix

| Area              | Supported                                                          |
| ----------------- | ------------------------------------------------------------------ |
| Python            | 64-bit CPython 3.10 and 3.11                                       |
| Operating systems | Windows                                                            |
| Base install      | CLI, logging, configuration, discovery, and dry-run pairing        |
| WSI input         | Formats supported by the installed OpenSlide build                 |
| Output            | TIFF/OME-TIFF, PNG/JPEG previews, and JSON manifests as documented |

Python 3.12 or newer is not supported in the 1.0 line because parts of the
scientific stack used by optional features do not yet share that support range.

## Feature installations

| Extra        | Capability                                            | Native requirement                     |
| ------------ | ----------------------------------------------------- | -------------------------------------- |
| `extraction` | Tissue, TMA/core, and paired-patch extraction         | OpenSlide, libvips                     |
| `orb`        | ORB registration and streamed aligned OME-TIFF export | OpenSlide, libvips                     |
| `valis`      | VALIS rigid/non-rigid registration                    | OpenSlide, libvips, VALIS requirements |
| `stain`      | Stain normalization                                   | None beyond its Python stack           |
| `cellcount`  | DAB-positive cell counting                            | OpenSlide for scanner WSIs             |
| `viz`        | Grid maps and image comparison                        | None beyond its Python stack           |

Install only the extras used by a workflow. Test and lint tools are deliberately
not exposed as a package extra.

## Compatibility expectations

- Public imports documented in the README are stable within `1.0.x`.
- JSON manifest fields may be added in patch releases; existing fields will not
  be renamed or removed without a deprecation period.
- `ReversiblePatchExtractor` is a compatibility adapter. New code should use
  `PatchExtractionConfig` and `run_patch_extraction`.
- Private names beginning with `_` can change without notice.

## Reporting a problem

Include the RocqiPath version, Python version, operating system, selected extras,
native OpenSlide/libvips versions, the shortest reproducible configuration, and
the complete traceback. Never attach patient data or identifiable slide images.
Prefer a small synthetic image that reproduces the failure.

## Release verification

A release is verified only after all of the following pass on Python 3.10 and
3.11:

1. editable installation and package metadata checks;
2. source/test compilation;
3. unit and scanner-free synthetic integration tests;
4. Ruff linting;
5. wheel construction; and
6. changelog and version review.

An annotated `v<version>` Git tag is created only from the commit that passed
that verification matrix.
