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

## Adding a feature

- Add or update a typed configuration dataclass.
- Keep single-item processing separate from the batch orchestrator.
- Record provenance, physical magnification, coordinates, and resolved config
  in JSON output when the operation changes image geometry.
- Add unit tests for pure logic and an integration test when WSI I/O is needed.
- Update the README quickstart and `__init__.py` exports.

## Checks

```bash
python -m compileall -q src tests
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
```

Use a small, non-identifiable test slide for local integration testing. Do not
commit patient data, model weights, generated output, or scanner exports.
