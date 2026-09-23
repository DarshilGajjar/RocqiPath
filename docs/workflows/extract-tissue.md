# Extract tissue

Use this for ordinary slides (biopsies, resections): every separate piece of
tissue becomes its own pyramidal TIFF.

```python
import rocqipath as rp

result = rp.extract_tissue("slides/", "regions/", target_magnification=10, source_magnification=40)
print(result.summary["regions"])
```

```console
rocqipath extract-tissue slides/ regions/ --target-magnification 10 --source-magnification 40
rocqipath extract-tissue slides/ regions/ --detector semantic   # TIAToolbox model (extra: semantic)
```

Regions are saved as `regions/tissue_extraction/<slide>/region_NNN.tif` with a
preview JPEG and a manifest recording the box on the original slide. Re-running
skips regions that already exist (`skip_existing`).

## Reference

::: rocqipath.api.extract_tissue

::: rocqipath.extraction.config.ExtractTissueConfig
