# Testing

```console
python -m pip install -e ".[test]"
python -m pytest            # about 200 tests, under a minute, no scanner files
ruff check src tests
cd studio-web && pnpm install && pnpm test && pnpm build
mkdocs build                # the docs extra; strict, so broken links fail
```

The `test` extra installs pip-packaged OpenSlide and libvips, so workflow
tests run everywhere. Tests needing TIAToolbox or VALIS skip when those are
absent.

## Golden snapshots

`tests/golden` runs every workflow on small deterministic synthetic slides
(`tests/golden/_data.py`) and compares a snapshot of the results:

- the output file tree;
- every JSON manifest;
- image sizes and mean colors;
- the returned summary.

This test guards against *behavior* changes during refactoring.

- **Changing how a workflow is called:** only `tests/golden/_calls.py` should
  change. The snapshots in `tests/golden/expected/` must not.
- **Intentionally changing outputs:** run
  `pytest tests/golden --update-golden` and review the JSON diff in the pull
  request.

Image means are compared with a tolerance of 1.0 because OpenCV and libvips
builds round slightly differently.

## Other contracts

| Test | Guards |
|---|---|
| `test_public_api.py` | the exact Tier-1 and Tier-2 surface and the shared calling convention |
| `test_config_compat.py` | every config field is documented; no config holds input/output folders; validation messages |
| `test_structure.py` | no two modules share a name; no helper is defined twice |
| `test_import_isolation.py` | `import rocqipath` loads no heavy dependency |
| `test_extras.py` | `rocqipath/extras.py` matches `pyproject.toml` |
| `test_chaining.py` | results and output folders feed later workflows |
| `studio/` | Studio API security, schema and jobs; the frontend fixture is current |
| `test_docs_examples.py` | the code on "Adding a workflow" runs |
