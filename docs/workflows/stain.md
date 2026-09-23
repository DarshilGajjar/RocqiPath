# Stain normalization

Two workflows share one config: train a normalizer on reference patches,
then apply it to other images so their colors match.

```python
import rocqipath as rp

weights = rp.train_stain_normalizer("reference_patches/", "stain/", method="macenko")
result = rp.normalize_stain("patches/", "stain/", normalizer=weights)
```

```console
rocqipath train-stain-normalizer reference_patches/ stain/ --method macenko
rocqipath normalize-stain patches/ stain/ --normalizer stain/stain_normalization/macenko_weights.npz
```

Saved weights can be reused later: the method is read from the
`<method>_weights.npz` filename. The normalizer classes in
[`rocqipath.stain`](../reference/building-blocks.md) fit and transform
single images in memory.

## Reference

::: rocqipath.api.train_stain_normalizer

::: rocqipath.api.normalize_stain

::: rocqipath.stain.config.StainConfig
