# Comparison figures

Publication figures showing an H&E slide, its ground-truth IHC and a
predicted IHC side by side, with zoomed crops of the same box in all three.

```python
import rocqipath as rp

rp.compare(["he.tif", "cd8.tif", "cd8_predicted.tif"], "figures/", zooms=["20x", "10x"], dpi=300)
```

```console
rocqipath compare he.tif cd8.tif cd8_predicted.tif figures/ --random-rois 3 --scale-bars
```

A case manifest JSON (with `stains.gt_he`, `gt_ihc`, `prediction_ihc`) can be
passed instead of the three paths.

## Reference

::: rocqipath.api.compare

::: rocqipath.viz.config.CompareConfig
