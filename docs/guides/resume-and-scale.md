# Resume, scale, and re-run

Whole-slide jobs run for hours. This guide covers stopping, restarting, and not
repeating work.

## Always dry-run first

```console
$ rocqipath study run mystudy --dry-run
```

Resolves every input and configuration and prints what would happen, without
touching a pixel. It costs a second and catches the mistakes that otherwise
cost an evening: a case missing its reference slide, a disabled stage, a
biomarker that matched nothing.

## Verify before you commit

```console
$ rocqipath study verify mystudy
```

Exits `1` on errors, which makes it usable as a gate:

```bash
rocqipath study verify mystudy && rocqipath study run mystudy
```

## Resuming

Stages skip work that is already complete. `tissue.skip_existing` is `true` by
default, and every artifact records the recipe hash it was produced under, so a
stage can tell whether existing output is still current.

To force a rebuild, either change the recipe (which changes the hash) or set
`skip_existing` to `false`:

```console
$ rocqipath study plan mystudy --set tissue.skip_existing=false
```

## Running stages independently

```console
$ rocqipath study run mystudy --stage alignment
$ rocqipath study run mystudy --stage patches
$ rocqipath study run mystudy --stage counts
```

Stages always execute in dependency order regardless of the order requested, so
`--stage counts --stage alignment` still runs alignment first.

By default a failing stage stops the run. To collect every failure in one pass:

```console
$ rocqipath study run mystudy --continue-on-error
```

## Splitting a cohort across machines

Studies are directories, so the simplest parallelism is to split by cases and
merge afterwards. Create two studies over the same archive with narrowed
patterns:

```toml
# machine A
pattern = '(?P<case>CRC-0\d\d)_(?P<stain>he|cd8)\.svs$'

# machine B
pattern = '(?P<case>CRC-1\d\d)_(?P<stain>he|cd8)\.svs$'
```

Because slides are referenced rather than copied, both studies read the same
archive without duplicating a byte.

## Staging and disk

Studies stage inputs as symbolic links, so a 300-slide cohort stages in under a
second and costs no disk. When symlinks are unavailable RocqiPath falls back to
hardlinks and then to copying — and warns you, because copying whole-slide
images is expensive.

```console
$ rocqipath study run mystudy --link-mode symlink
```

Forcing `symlink` makes the failure loud instead of slow. On Windows, enable
Developer Mode to allow symlinks without an elevated shell.

## Where the time goes

| Stage | Typical bottleneck | What helps |
| --- | --- | --- |
| `survey` | Metadata reads | `--no-stat` on the index step for slow network storage |
| `alignment` | Feature matching and warping | `orb` instead of `valis` where a rigid fit suffices |
| `patches` | Decoding and resizing | `max_workers`, local staging, larger `stride` |
| `stain` | Fitting, especially `vahadane` | Lower `max_train_patches`; fit on a selection |
| `counts` | Segmentation | Restrict via `chromogen_stains` |

## Re-running is not re-computing

The cheapest optimisation available is to not re-extract. A different quality
threshold is a new [selection](../reference/selections.md), computed in seconds
over a manifest you already have:

```console
$ rocqipath study select mystudy strict-v2 --min tissue_fraction=0.7
```

If you find yourself re-running `patches` to change a threshold, the threshold
is in the wrong place.
