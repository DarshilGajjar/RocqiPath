# Chaining workflows

A workflow's `inputs` can be:

1. **Paths:** a file, a folder, or a list of them.
2. **A `Result`** returned by an earlier workflow.
3. **An output folder** containing a `rocqipath.json`, the same thing on disk.

Each workflow declares which item roles it accepts, so passing an earlier
result selects the right files automatically:

```python
import rocqipath as rp

aligned = rp.align("pairs/", "aligned/", backend="orb")

# Each aligned slide is paired with the reference it was aligned to.
patches = rp.extract_patches(aligned, "patches/", patch_size=512)

# Only the H&E patches train the normalizer; only they are normalized.
weights = rp.train_stain_normalizer(patches, "stain/", method="macenko", stains=["he"])
rp.normalize_stain(patches, "stain/", normalizer=weights, stains=["he"])

# Aligned slides are counted; QC figures and references are ignored.
counts = rp.count_cells(aligned, "counts/", label="CD8")
```

The same works with folders, for example in a later session or from the
command line:

```console
rocqipath extract-patches aligned/ patches/ --patch-size 512
rocqipath count-cells aligned/ counts/ --label CD8
```

When a result holds no acceptable files, the error explains what it holds and
what was expected:

```text
ValueError: the align result holds aligned, figure, reference files;
this workflow needs one of: patch, region, core
```

In [Studio](../studio.md), "Use as input…" on a finished job does the same.
