# Count cells

Counts brown (DAB-positive) cells on IHC slides. Each tissue patch gets its
own Otsu threshold within an HSV brown color gate, and counts, tissue area and
density are reported per slide.

```python
import rocqipath as rp

result = rp.count_cells("cd8_slides/", "counts/", label="CD8", source_magnification=40)
for slide in result.summary["results"]:
    print(slide["slide"], slide["total_positive"], slide["density_per_mm2"])

# Compare a predicted IHC slide against the real one, patch by patch:
rp.count_cells("case01_CD8.svs", "counts/", compare_to="case01_CD8_predicted.tif")
```

```console
rocqipath count-cells cd8_slides/ counts/ --label CD8
rocqipath count-cells real.svs counts/ --compare-to predicted.tif --max-plots 20
```

Comparisons write an Excel sheet of per-patch counts and comparison figures.

## Reference

::: rocqipath.api.count_cells

::: rocqipath.counting.config.CountCellsConfig
