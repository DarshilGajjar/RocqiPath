# Contributing to RocqiPath

## Design rules

1. Put new behavior in the closest existing subpackage. Create a new top-level
   module only for genuinely shared infrastructure.
2. Express zoom as physical `target_magnification`; do not expose a pyramid
   index as magnification.
3. Use `OutputLayout` so a main pipeline writes to
   `<root>/<module>/<individual_item>`.
4. Put reusable slide I/O in `SlideReader`; do not add another OpenSlide/PIL
   wrapper to a feature module.
5. Raise a RocqiPath exception for expected operational failures. Do not catch
   broad exceptions unless the pipeline can add useful case-level context.
6. Add type hints and a NumPy-style docstring to every function, method, and
   class, including private helpers with non-obvious behavior.
7. Preserve public names when practical. Add a deprecation path when removing
   a public symbol.
8. Put shared filesystem discovery in `rocqipath.utils`; do not add another
   recursive scanner to a feature module.
9. Use `rocqipath.logger` for library status output. Do not add `print()`-based
   progress protocols or configure independent logging sinks.

## Adding a feature

- Add or update a typed configuration dataclass.
- Keep single-item processing separate from the batch orchestrator.
- Record provenance, physical magnification, coordinates, and resolved config
  in JSON output when the operation changes image geometry.
- Add unit tests for pure logic and an integration test when WSI I/O is needed.
- Update the README quickstart and `__init__.py` exports.

## Checks

```bash
python -m pip install -e ".[orb,cellcount,viz]"
python -m pip install "pytest>=7.4" "ruff>=0.4"
python -m compileall -q src tests
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
```

Use a small, non-identifiable test slide for local integration testing. Do not
commit patient data, model weights, generated output, or scanner exports.

## Release checklist

1. Confirm `pyproject.toml` contains the intended static version.
2. Run the full check sequence on Python 3.10 and 3.11 with OpenSlide and
   libvips available.
3. Build a wheel and verify the `rocqipath` import and console entry point from
   an isolated environment.
4. Move user-visible changes from `Unreleased` into the dated changelog entry.
5. Commit the exact verified tree, then create the annotated `v<version>` tag.
6. Push the commit and tag only after reviewing the remote branch for new work.
