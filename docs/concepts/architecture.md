# RocqiPath architecture

RocqiPath is organized in layers so scientific algorithms remain reusable without pulling
unrelated optional dependencies into a process.

## Dependency direction

Dependencies point downward through these layers:

1. `core` — domain primitives and shared infrastructure.
2. `utils` — stateless helpers operating on primitives.
3. `config` — typed, serializable pipeline configuration.
4. Feature packages — `registration`, `extraction`, `stain`, `analysis`, and
   `visualization`.
5. `cli` — argument parsing and command dispatch.

A higher layer may import a lower layer. A lower layer must not import a higher one.
Feature packages should not import implementations from another feature package. When two
features need the same behavior, move that behavior to `core` if it understands a
RocqiPath domain concept, or to `utils` if it is stateless and works on generic values.

`core` and `utils` must remain importable without presentation or logging frameworks.
Heavy libraries such as NumPy, OpenCV, Pillow, pyvips, OpenSlide, matplotlib,
scikit-image, TIAToolbox, and VALIS must not be imported at module scope in those two
packages. A narrowly scoped function-local import is acceptable when a shared primitive
genuinely needs one.

## Package responsibilities

| Package | Responsibility | Typical contents |
|---|---|---|
| `core` | RocqiPath domain primitives and process infrastructure | magnification, slide access, tissue definitions, output layout, exceptions, logging |
| `utils` | Stateless transforms and file helpers | discovery, naming, image I/O, geometry, manifests, validation |
| `config` | Typed inputs to feature workflows | dataclasses, shared validation, serialization |
| `registration` | Fixed/moving WSI alignment | registrar façade, VALIS and ORB backends, export, QC |
| `extraction` | Tissue, TMA, and patch workflows | detection, extraction engines, reversible reconstruction |
| `stain` | Stain normalization | normalizer algorithms, weight formats, train/apply workflows |
| `analysis` | Quantitative pathology | DAB-positive cell counting and reports |
| `visualization` | Exploratory and publication figures | grids, pairs, overlays, comparisons, thumbnails |
| `cli` | User interaction only | parsers and command handlers |

## Where new code belongs

Use this decision procedure:

1. If the code is a config dataclass or config validator, place it in `config`.
2. If two or more feature packages need it and it defines a domain primitive or holds
   state, place it in `core`.
3. If it accepts generic primitives, is stateless, and returns generic primitives, place
   it in `utils`.
4. If it knows about one pipeline, stain, registration backend, output convention, or
   scientific workflow, keep it in that feature package.
5. If it parses arguments or selects a workflow, place it in `cli`.

Do not choose a location based only on file size. Split modules at responsibility
boundaries: orchestration, detection, transformation, serialization, reporting, and
export are usually separate units.

## Public API and compatibility

Subpackage `__init__.py` files are the supported public façades. Internal implementations
may move, but documented imports remain available through those canonical feature exports.
Deprecated flat and historical module paths are not retained.

Configuration and numeric image-processing behavior are compatibility boundaries too.
Thresholds, coordinate spaces, resize methods, and serialization keys must not change
during structural work. Add characterization tests before consolidating duplicate
implementations.

## Coordinate and magnification model

Public workflows use physical objective magnification, not arbitrary pyramid indices.
`MagnificationPlan` resolves a slide's base objective, source pyramid level, residual
resize, and coordinate scale. Document every image coordinate as one of:

- level-0 pixels;
- pixels at target magnification;
- pixels in a named pyramid level;
- micrometres; or
- a dimensionless fraction.

Use `SlideReader` for slide access and `OutputLayout` for output paths so these conventions
stay consistent across feature packages.

## Optional dependencies

Feature imports are guarded at the package façade. Each command imports its feature backend
only when executed, so `rocqipath --help` remains useful in a lightweight installation.
When adding a backend, keep its imports inside the feature package and add it to the
appropriate optional dependency extra rather than the base dependency set.


## The study layer

`rocqipath.study` sits alongside the feature packages and is imported by the
CLI. It may import feature packages; **feature packages must not import it.**

```
core  ->  utils  ->  config  ->  feature packages  ->  cli
                                 (extraction, registration,
                                  stain, analysis, visualization)
                                        ^
                                        |
                                      study
```

| Module | Responsibility |
| --- | --- |
| `study.paths` | `ROCQIPATH_HOME` resolution and the on-disk layout |
| `study.descriptor` | Parse and validate `study.toml`; render the template |
| `study.index` | Discover slides, decode `slide_uid`, derive pairs |
| `study.survey` | Measure slides; degrade gracefully when one is unreadable |
| `study.verify` | Pre-flight checks with an actionable fix per issue |
| `study.recipe` | Resolve and hash the plan |
| `study.manifests` | JSONL artifact manifests plus sidecars |
| `study.selection` | The rule language and saved QC views |
| `study.staging` | Present indexed slides to directory-based pipelines |
| `study.stages` | **The integration seam.** Recipe → existing typed configs → existing pipeline calls |
| `study.results` | Aggregate manifests into tidy tables |
| `study.study` | The `Study` facade |
| `study.doctor` | Environment diagnostics |

### Rules for this layer

1. **`study.stages` is the only module that calls a pipeline.** If a pipeline
   signature changes, that file is the only place a study needs updating.
2. **Nothing here re-implements image processing.** A stage adapter resolves
   inputs, builds a typed config, calls the existing entry point, and records
   what happened.
3. **Stage failures become results, not tracebacks.** `run_stage` returns a
   `StageResult` with a status and an actionable error, so one failing stage
   never aborts a cohort halfway with a stack trace.
4. **`study.paths`, `study.descriptor`, `study.index`, `study.recipe`,
   `study.manifests`, and `study.selection` import only the standard library
   and `core`.** They work on a base install with no image backend, which is
   what lets `init`, `index`, `verify`, and `plan` run anywhere.
