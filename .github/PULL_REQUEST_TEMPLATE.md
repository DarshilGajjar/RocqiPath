## What this changes

<!-- One or two sentences. Link the issue it closes, if any. -->

## Why

<!-- The problem being solved. If it changes behaviour, say what breaks. -->

## Checklist

- [ ] No patient data, identifiers, or identifying filenames anywhere in this
      PR — including tests, fixtures, and screenshots
      ([SECURITY.md](../SECURITY.md))
- [ ] `python -m pytest` passes
- [ ] `python -m ruff check src tests` passes
- [ ] `python -m ruff format --check src tests` passes
- [ ] New public functions and classes have type hints and NumPy-style
      docstrings ([CONTRIBUTING.md](../CONTRIBUTING.md))
- [ ] Zoom is expressed as physical `target_magnification`, never a pyramid
      index ([magnification](../docs/concepts/magnification.md))
- [ ] Dependency direction preserved: `core` → `utils` → `config` → feature
      packages → `cli`
- [ ] Documentation updated where behaviour changed
- [ ] `CHANGELOG.md` updated under `[Unreleased]`

## If this touches a stage that writes artifacts

- [ ] It writes **every** artifact it produces and records measurements in a
      manifest; it applies no quality threshold of its own
      ([QC philosophy](../docs/concepts/qc-philosophy.md))
- [ ] Manifest rows carry a `uid` so selections can reference them
- [ ] The recipe hash is recorded on the output

## Testing

<!-- What you ran. Note anything that needs real scanner files and so cannot
     run in CI — those tests stay local and must use non-identifiable data. -->
