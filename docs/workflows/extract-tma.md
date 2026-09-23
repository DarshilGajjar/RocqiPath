# Extract TMA cores

Use this for tissue microarrays and other slides with many round samples.
Slides are grouped into blocks by the sample ID in their filenames and
recognized as H&E (`HE`, `HnE`, `H&E`) or a known marker (`CD8`, `CD3`,
`CD31`, `CD56`, `CD68`, `CD163`, `CAIX`, `MECA79`, `MHC1`, `PDL1`). Other
markers are recognized when named in `stains`. Cores are found on the H&E
slide and the same boxes are cut from every IHC slide of the block.

```python
import rocqipath as rp

rp.extract_tma("tma_slides/", "cores/", source_magnification=40, stains=["HE", "CD8"])
```

```console
rocqipath extract-tma tma_slides/ cores/ --stains HE CD8 --min-circularity 0.6
```

`--no-only-circles` disables the circularity gate; `--no-per-stain-detection`
reuses the H&E boxes for every stain.

## Reference

::: rocqipath.api.extract_tma

::: rocqipath.extraction.config.ExtractTMAConfig
