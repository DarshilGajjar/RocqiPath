# Extract patch pairs

Use this after [alignment](align.md) to make pixel-matched H&E/IHC patch
pairs, for example as training data. Each aligned slide is paired with the
reference it was aligned to; patches are kept where the reference has enough
tissue.

```python
import rocqipath as rp

aligned = rp.align("pairs/", "aligned/", backend="orb")
patches = rp.extract_patches(aligned, "patches/", patch_size=512, tissue_threshold=0.5)
he_patches = [item for item in patches if item.meta["stain"] == "he"]
```

```console
rocqipath extract-patches aligned/ patches/ --patch-size 512
```

Each case folder holds `<case>_<stain>_patch_<id>.png` files and a
`<case>_metadata.json` recording every patch position and the slide size,
the layout [`ReversiblePatchExtractor.reconstruct_wsi`](../reference/building-blocks.md)
uses to stitch (processed) patches back into a pyramidal slide.

Aligned slides that were not produced by `rp.align` can be used too: pass the
folder laid out as `<biomarker>/<sample>_<reference_name>/*.ome.tiff` and
`reference=` the folder of reference slides.

## Reference

::: rocqipath.api.extract_patches

::: rocqipath.extraction.config.ExtractPatchesConfig
