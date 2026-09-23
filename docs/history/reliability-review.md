# RocqiPath reliability review

RocqiPath's feature-based organization is a useful foundation. This review found
concrete gaps at image I/O, reconstruction, optional imports, and saved stain
state. The fixes preserve public imports and function signatures. A rewrite is
not justified by these findings.

## Reproduced and fixed

| Area | Before | After |
| --- | --- | --- |
| Image output | OpenCV could return `False`; stain application would still count the image as processed. | The shared writer raises `OSError`, allowing the pipeline to count a failure. |
| Slide regions | PIL crops entirely beyond any image edge raised invalid-coordinate errors. | These reads return the requested white-padded RGBA region; partial overlap remains intact. |
| Magnification | Non-object JSON sidecars raised `AttributeError`; infinity prevented trying a valid directory manifest. | Invalid sidecars are skipped and positive finite fallback values are considered. |
| Weight filenames | NumPy appended `.npz`, leaving training's returned custom path nonexistent. | Archives are written to the exact requested path. |
| Macenko weights | Loading restored the stain matrix and concentrations but omitted scaling, causing `transform` to crash. | Scaling is reconstructed from saved concentrations, including legacy archives. |
| Vahadane weights | Saved archives omitted the concentration scaling needed by `transform`. | New archives preserve scaling. Old matrix-only archives raise a retraining instruction because the missing state cannot be recovered. |
| Reconstruction | Averaging overlapping patches left uncovered pixels black. | Uncovered pixels remain white, consistent with direct-paste reconstruction. |
| Optional imports | Importing extraction required libvips through a reconstruction helper, even for scanner-free patch work. | The reconstruction module imports libvips only when exporting a pyramid. The global fake-module test workaround was removed. |
| Development checks | CI ran package imports and CLI help but no regression suite. | A `test` extra, documented commands, and CI test/lint steps make the checks repeatable. |

New defect tests were run against the broken behavior before applying fixes.
The existing eight Ruff findings were also resolved without behavioral changes.

## Verification

| Check | Result |
| --- | --- |
| Initial suite, Python 3.11 | 65 passed |
| Final clean `.[test]` environment, Python 3.10.20 | 81 passed, 4 skipped |
| Final clean `.[test]` environment, Python 3.11.9 | 81 passed, 4 skipped |
| Real TIAToolbox stain persistence tests in the existing Python 3.12.14 environment | 9 passed, including fit/save/load/transform comparisons for Reinhard, Macenko, and Vahadane |
| Ruff, source and tests | Passed |
| Source distribution and wheel build | Passed |
| Installed wheel, no optional dependencies | Package import and all six CLI help checks passed |

The four clean-environment skips are the README extraction example requiring
libvips and three real TIAToolbox algorithm tests. Backend-independent archive
compatibility tests still run in the default suite. The Python 3.12 experiment
is supplemental evidence, not a change to the supported Python range.

An independent review found no actionable issues in the core reliability diff.
GitHub's Linux matrix has been configured but has not been executed locally.

## Organization and maintenance

- Keep the five feature packages as the public entry points. Shared slide reads,
  physical magnification, and output paths already have clear owners in `core`.
- Keep configuration types in `config` and narrowly scoped helpers in `utils`.
  This pass required small changes at those existing boundaries.
- `config/registration.py` is roughly 1,850 lines, much of it documentation.
  Moving its documentation to an advanced reference could improve navigation;
  splitting classes across new modules is not required for these fixes.
- The legacy reversible extractor and config-driven patch workflow still have
  parallel orchestration. Consolidate only with explicit compatibility tests for
  filenames, manifests, and magnification behavior.

## Remaining validation limits

Synthetic tests establish software behavior, not registration quality or cell
counting accuracy on real tissue. This pass did not run full scanner-slide ORB
or VALIS registration/export, semantic model inference, or large-slide memory
benchmarks. Those need representative slides and the corresponding native/model
dependencies. Real TIAToolbox normalization on supported Python versions remains
a useful integration check; this run used the pre-existing Python 3.12 environment.

Reconstruction still allocates a full slide canvas, and stain training collects
patches before fitting. Their large-input memory behavior was not redesigned.
Package builds also emit existing setuptools license-metadata deprecation
warnings; no licensing terms were changed.
