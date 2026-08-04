# CLI reference

```console
$ rocqipath --help
$ rocqipath <command> --help
```

Running `rocqipath` with no arguments opens the guided menu. Pass
`--interactive` to open it explicitly.

## `rocqipath doctor`

Prints Python, platform, native libvips and OpenSlide runtimes, installed
optional extras, the resolved workspace root, and anything likely to break a
run. Exits `1` when problems are detected.

```console
$ rocqipath doctor
$ rocqipath doctor --json
```

Paste the output into a bug report. The issue template asks for it.

## `rocqipath study`

All subcommands accept `--home PATH` to override `ROCQIPATH_HOME`.

### `init`

```console
$ rocqipath study init NAME [--source DIR]... [--stain KEY]... [--magnification X] [--overwrite]
```

Creates the study directory and writes a commented `study.toml`. The first
`--stain` becomes the reference stain.

### `index`

```console
$ rocqipath study index NAME [--no-stat]
```

Walks every declared source, decodes filenames into identity, and writes
`index.jsonl`. Files that do not match the pattern are reported as warnings.
`--no-stat` skips size, mtime, and digest reads — useful on slow network
storage.

### `survey`

```console
$ rocqipath study survey NAME [--quiet]
```

Opens each slide once and records objective magnification, microns per pixel,
pyramid downsamples, dimensions, and vendor. Nothing is read at full
resolution.

### `verify`

```console
$ rocqipath study verify NAME [--json]
```

Reports every problem that would break a run, each with the edit that resolves
it. Exits `1` when there are errors. Run this before anything expensive.

### `plan`

```console
$ rocqipath study plan NAME [--set STAGE.KEY=VALUE]...
```

Resolves settings into `recipe.json` and prints the hash. Values are parsed as
JSON where possible, so `--set patches.patch_size=256` gives an integer and
`--set alignment.method=orb` gives a string.

### `run`

```console
$ rocqipath study run NAME [--stage STAGE]... [--dry-run]
                           [--link-mode auto|symlink|hardlink|copy]
                           [--continue-on-error]
```

Executes stages in dependency order: `tissue`, `alignment`, `patches`,
`stain`, `counts`. Defaults to all of them.

`--dry-run` resolves inputs and configuration and prints the plan without
executing anything. Always worth doing first.

`--link-mode` controls how inputs are staged for the directory-based pipelines.
`auto` tries symlink, then hardlink, then copy, and warns when it has to copy.

### `select`

```console
$ rocqipath study select NAME SELECTION [--stage STAGE] [--manifest NAME]
                                        [--rule EXPR] [--min FIELD=VALUE]...
```

Evaluates a rule over a stage manifest and saves the result. Defaults to the
`patches` stage. See [selections](selections.md).

### `results`

```console
$ rocqipath study results NAME [--stage STAGE] [--selection NAME]
                               [--group-by case,stain] [--csv PATH] [--limit N]
```

Aggregates a manifest into a tidy table, optionally through a selection.

### `show` and `list`

```console
$ rocqipath study show NAME
$ rocqipath study list
```

## Pipeline commands

The original commands are unchanged and remain the direct route when you are
not using a workspace.

| Command | Purpose |
| --- | --- |
| `rocqipath align` | Register paired whole-slide images |
| `rocqipath extract` | Extract WSI tissue regions or TMA cores (`--mode wsi\|tma`) |
| `rocqipath stain` | Train or apply a stain normalizer |
| `rocqipath count` | Count DAB-positive cells |
| `rocqipath compare` | Publication-quality WSI comparison figures |

Each accepts `--interactive` to be prompted for its settings.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Verification errors, a failed stage, or a usage problem |
| `130` | Interrupted with Ctrl-C |
