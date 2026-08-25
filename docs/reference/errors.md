# Errors: message, cause, fix

Every RocqiPath error inherits from `WSIProcessingError`, so one `except`
clause catches all of them:

```python
from rocqipath.core.exceptions import WSIProcessingError

try:
    study.run("alignment")
except WSIProcessingError as exc:
    logger.error("Pipeline failed: {}", exc)
```

Some errors also inherit a built-in for compatibility: `SlideNotFoundError`,
`StudyNotFoundError`, and `DescriptorNotFoundError` are all `FileNotFoundError`
subclasses.

## Study and configuration

**`No study at <path>`**
The study directory does not exist under the resolved workspace root.
→ `rocqipath study init <name> --source <dir>`, or check `ROCQIPATH_HOME` with
`rocqipath doctor`.

**`No study descriptor at <path>`**
The directory exists but has no `study.toml`.
→ Re-run `init`, or restore the file.

**`study.toml must declare a 'name'`**
→ Add `name = "..."` at the top level.

**`Source pattern must define named group(s): stain`**
The regex is missing a required capture group.
→ The pattern must capture `case` and `stain`; `section` is optional.

**`Multiple reference stains declared`**
→ Exactly one `[stains.*]` table may carry `role = "reference"`.

**`Reading study.toml on Python 3.10 requires the 'tomli' backport`**
→ `python -m pip install tomli`, or upgrade to Python 3.11.

## Index and identity

**`Filename did not match the source pattern: <path>`** *(warning)*
→ Adjust the `pattern` in `[[sources]]`. Nothing is silently dropped; every
unmatched file is listed.

**`Stain 'x' is not declared in study.toml`** *(warning)*
→ Add a `[stains.x]` table, or narrow the pattern so the file is not matched.

**`Duplicate slide_uid 'x': <a> collides with <b>`**
Two files decode to the same identity.
→ Add a `section` group to the pattern, or exclude one file under
`[overrides]`.

**`Case has no reference slide, so no pair can be derived`**
→ Add the missing reference slide, or exclude the case.

## Magnification

**`Slide objective magnification is missing`**
The scanner wrote no objective-power tag and no fallback was supplied.
→ Add it per slide:

```toml
[overrides."CASE-1__he__s01"]
source_magnification = 80.0
```

**`target_magnification (40x) cannot exceed the slide's level-0 magnification (20x)`**
→ RocqiPath will not invent resolution. Lower `default_magnification`, or
exclude the slide. See [magnification](../concepts/magnification.md).

**`Slide is indexed but absent from the survey`** *(warning)*
→ `rocqipath study survey <name>`

## Native runtimes

**`OSError: cannot load library 'libvips.so.42'`**
→ Install libvips; on Windows add its `bin` to PATH and reopen the terminal.
See [native dependencies](../start/native-dependencies.md).

**`ModuleNotFoundError: No module named 'pyvips'`**
→ `python -m pip install -e ".[orb]"`

**`Stage 'x' needs optional dependencies that are not installed`**
→ Install the matching extra. `rocqipath doctor` lists which are present.

## Stages

**`Patch extraction needs aligned output`**
→ `rocqipath study run <name> --stage alignment` first.

**`Stain normalization needs extracted patches`**
→ `rocqipath study run <name> --stage patches` first.

**`Stage 'x' is disabled in recipe.json`** *(warning)*
→ Set `"enabled": true` for that stage, or re-run `plan`.

**`N slide(s) had to be copied because neither symlinks nor hardlinks were available`** *(warning)*
→ Enable Developer Mode on Windows, or keep the workspace on the same volume as
the archive. Copying whole-slide images is slow and wastes disk.

## Selections

**`Could not parse rule '...'`**
→ Check the syntax. See the [rule language](selections.md#the-rule-language).

**`Unsupported expression element: <node>`**
The rule uses syntax outside the grammar — an import, attribute access, a
comprehension, a lambda.
→ Rules allow comparisons, boolean logic, arithmetic, membership tests, and the
`percentile`, `is_null`, and `lower` helpers. Nothing else.

**`No selection named 'x'`**
→ `study.selections()` lists what exists.

## Manifests

**`No <stage> manifest at <path>`**
→ Run the stage first.

**`line N is not valid JSON`**
The manifest was truncated, most likely by an interrupted write.
→ Re-run the stage. Manifest sidecars are written even after an exception, so
compare `n_rows` against the line count to confirm.

## Still stuck

Run `rocqipath doctor`, then open an issue with its output attached. **Never
attach patient slides, filenames, or identifiers** — see
[SECURITY.md](../../SECURITY.md).
