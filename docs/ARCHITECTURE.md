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
5. `cli` — argument parsing, interactive prompts, and command dispatch.

A higher layer may import a lower layer. A lower layer must not import a higher one.
Feature packages should not import implementations from another feature package. When two
features need the same behavior, move that behavior to `core` if it understands a
RocqiPath domain concept, or to `utils` if it is stateless and works on generic values.

`core` and `utils` must remain importable with only the base dependencies, `rich` and
`loguru`. Heavy libraries such as NumPy, OpenCV, Pillow, pyvips, OpenSlide, matplotlib,
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
| `cli` | User interaction only | parsers, prompts, command handlers |

## Where new code belongs

Use this decision procedure:

1. If the code is a config dataclass or config validator, place it in `config`.
2. If two or more feature packages need it and it defines a domain primitive or holds
   state, place it in `core`.
3. If it accepts generic primitives, is stateless, and returns generic primitives, place
   it in `utils`.
4. If it knows about one pipeline, stain, registration backend, output convention, or
   scientific workflow, keep it in that feature package.
5. If it parses arguments, prompts the user, or selects a workflow, place it in `cli`.

Do not choose a location based only on file size. Split modules at responsibility
boundaries: orchestration, detection, transformation, serialization, reporting, and
export are usually separate units.

## Public API and compatibility

Subpackage `__init__.py` files are the supported public façades. Internal implementations
may move, but documented imports remain available through re-exports. Deprecated flat or
historical module paths are small compatibility shims; new code should import from the
canonical package named in the shim.

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
