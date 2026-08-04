# FAQ

### Do I have to use studies?

No. Every pipeline function works exactly as it always has, with explicit
paths. Studies are a layer on top for cohorts you will re-run or publish. See
[migrating to studies](start/migrating-to-studies.md).

### Why not just use pyramid levels?

Because a level number means a different magnification on every scanner, and
nothing in the file format warns you. Mixing them produces a dataset where the
model can learn scanner identity as a confounder. See
[magnification](concepts/magnification.md).

### Why does RocqiPath refuse to give me 40x from a 20x scan?

Because that would be interpolation presented as measurement. Upsampled pixels
carry no information the microscope did not capture, and once they are in a
cohort nothing distinguishes them from real ones.

### Why does my study write no patches when tissue_threshold is 0?

It writes *all* of them. Zero is not a bug — expensive stages measure and
selections decide. Apply your threshold with
`rocqipath study select <name> <selection> --min tissue_fraction=0.6`. See
[QC philosophy](concepts/qc-philosophy.md).

### Do studies copy my slides?

No. Slides are referenced where they are. Stages stage inputs as symbolic links
so a cohort stages in under a second and costs no disk. Copying only happens
when neither symlinks nor hardlinks are available, and RocqiPath warns when it
has to.

### Can one H&E serve several biomarkers?

Yes, and that is the intended pattern. Pairs are derived as case × (reference,
moving), so a single H&E backs CD8, CD31, and anything else without being
duplicated.

### My case IDs contain underscores. Will that break?

No. `slide_uid` separates fields with a double underscore
(`BLOCK_12_A__cd8__s03`), specifically because accession numbers routinely
contain single ones.

### Do I have to rename my slides?

No. Adjust the `pattern` in `[[sources]]` to match the names you already have.
Renaming gigabytes of archived slides is exactly what the regex avoids.

### Where does `ROCQIPATH_HOME` default to?

`~/rocqipath`. Set it explicitly to a large, fast volume — studies reach
hundreds of gigabytes. `rocqipath doctor` shows the resolved value.

### Which Python version?

3.10 or 3.11, 64-bit. Not 3.12 or newer: the TIAToolbox and Numba stack does
not support them yet.

### Do I need libvips and OpenSlide?

For real slide work, yes. Without them RocqiPath falls back to PIL and can only
open ordinary TIFFs. See [native dependencies](start/native-dependencies.md).

### `orb` or `valis`?

Start with `orb`: lighter, faster, rigid. Move to `valis` when QC shows
deformation a rigid transform cannot absorb.

### Can I edit `recipe.json` by hand?

Yes — it exists to be read and edited. Note that re-running
`rocqipath study plan` regenerates it, so keep durable changes in `study.toml`
and use recipe edits for experiments.

### What exactly does the recipe hash cover?

Everything except `generated_at`, `recipe_hash`, and `rocqipath_version`.
Regenerating an unchanged plan yields an unchanged hash; changing any decision
changes it.

### How do I make a selection reproducible in a paper?

Cite the selection name, its rule, and the recipe hash. All three are stored in
`selections/<name>.json`.

### Can a rule run arbitrary Python?

No. Rules are evaluated through a whitelisted AST walk, never `eval`. Imports,
attribute access, comprehensions, lambdas, and any call outside `percentile`,
`is_null`, and `lower` raise `RuleError`.

### Does `to_dataframe()` need pandas?

Yes, and RocqiPath deliberately does not depend on it. Use `to_dicts()` or
`to_csv()` if you would rather not install it.

### Something is broken. What should I attach to the issue?

The output of `rocqipath doctor`. **Never** attach patient slides, filenames,
or identifiers — see [SECURITY.md](../SECURITY.md).
