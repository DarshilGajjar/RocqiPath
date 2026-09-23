# Architecture

```text
src/rocqipath/
  __init__.py      Tier 1: the public API, loaded lazily
  api.py           every workflow, with its full docstring
  registry.py      @workflow, Result, Item, run(), list_workflows()
  errors.py        exception hierarchy
  extras.py        which modules each pip extra provides
  io/              slides, magnification, discovery, naming, images, manifests, inputs
  tissue/          tissue masks and region detectors (Otsu, TIAToolbox)
  extraction/      config.py + tissue regions, TMA cores, patch pairs, reconstruction
  alignment/       config.py + pipeline, WSIRegistrar, ORB and VALIS backends, export, QC
  stain/           config.py + normalizers and batch train/apply
  counting/        config.py + PositiveCellCounter and reporting
  viz/             config.py + comparison, overlays, grids, thumbnails
  _internal/       private helpers: BaseConfig, console, logging, validation, geometry
  cli/             the command line, generated from the registry
  studio/          local web server (catalog, jobs, tiles) + built interface in static/
```

## Three tiers

1. **`rocqipath`**: workflows, configs, `Result`, `open_slide` and errors.
   This is what the docs, notebooks and CLI are written against.
2. **`rocqipath.<package>`**: documented building blocks
   (`WSIRegistrar`, normalizer classes, tissue masks, …).
3. **`_internal` and underscore names**: private, with no stability promise.

Subpackages are named with nouns (`alignment`) and workflows with verbs
(`rp.align`), so a function never shadows a package.

## One definition, three interfaces

A workflow is one function in `api.py` decorated with
`@workflow(name, config=..., extra=..., inputs=InputSpec(...))`. The decorator:

- builds and validates the config from keywords;
- resolves `inputs` into `Item`s (paths, earlier results, output folders);
- creates the output folder, runs the function, writes `rocqipath.json` and
  returns a `Result`.

The registry then feeds:

- **Python:** `rp.<name>` is the decorated function.
- **CLI:** `cli/__init__.py` makes one subcommand per workflow and one flag
  per config field. Types come from the dataclass, help from the docstring.
- **Studio:** `studio/catalog.py` serves the same schema at
  `/api/workflows`. The React form renders any schema.

## Docstrings are the documentation

Config classes document every field in their numpy `Parameters` section.
`_internal.base_config.field_help` parses it for CLI `--help` and Studio
tooltips, and mkdocstrings renders it on this site. A test fails if a field
is undocumented.

Field metadata controls visibility:

- `metadata=ADVANCED` hides a rarely changed field behind `--help-all` and
  Studio's advanced section.
- `metadata=LOCAL_ONLY` marks paths and raw backend passthroughs that Studio
  must never accept from a browser.

## Heavy dependencies stay lazy

`import rocqipath` and every `config.py` import nothing heavier than the
standard library. OpenCV, libvips, OpenSlide, TIAToolbox and VALIS are
imported inside functions. `tests/test_import_isolation.py` enforces this.
