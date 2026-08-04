# Normalise stains

**Goal:** reduce colour variation between slides, scanners, and staining runs
so that downstream analysis measures biology rather than laboratory drift.

**You need:** the `stain` extra.

## Choosing a method

| Method | How it works | Use when |
| --- | --- | --- |
| `reinhard` | Matches mean and standard deviation in LAB colour space | Fast, robust, a good default when stains are already similar |
| `macenko` | Estimates stain vectors by singular value decomposition of optical density | Standard choice for H&E; handles genuine colour differences |
| `vahadane` | Sparse non-negative matrix factorisation | Best separation, noticeably slower; worth it for difficult IHC |

Start with `macenko`. Move to `vahadane` when a chromogen and a counterstain
are being confused.

## With a study

```console
$ rocqipath study plan mystudy --set stain.normalizer=vahadane
$ rocqipath study run mystudy --stage stain
```

## Without a study

```python
from rocqipath.stain import (
    StainNormalizationConfig,
    run_stain_normalization_apply,
    run_stain_normalization_train,
)

cfg = StainNormalizationConfig(
    n_type="macenko",
    stains=["he"],
    fit_min_tissue=0.1,
    max_train_patches=1000,
)
run_stain_normalization_train("./patches", "./results", cfg)
run_stain_normalization_apply("./patches", "./results", cfg)
```

Training and applying are separate calls on purpose: fit once on a
representative sample, then apply the same transform everywhere. Refitting per
batch reintroduces exactly the variation you are trying to remove.

## Fitting well

`fit_min_tissue` excludes mostly-background patches from fitting. Background
has no stain vectors to estimate, and including it drags the fit toward white.

`max_train_patches` caps the fitting sample. A thousand well-chosen patches
usually beats ten thousand arbitrary ones, and fits in a fraction of the time.

If you have already made a selection, fit on it — a strict selection is a
better training sample than the raw manifest:

```python
selection = study.selection("strict")
```

## When not to normalise

Normalisation is not free. It can suppress genuine signal when intensity is
itself the measurement — faint versus strong DAB, for example. If you are
counting chromogen-positive cells, consider counting on unnormalised images and
using normalisation only for the visual comparisons.

Whichever you choose, record it. The recipe already does.
