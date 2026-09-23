# Align slides

Registers moving slides (usually IHC) onto reference slides (usually H&E)
and exports each aligned slide as a pyramidal OME-TIFF in the reference's
coordinates.

```text
pairs/
└── CD8/                 # one pair folder per marker
    ├── he/  case01_HE.svs  case02_HE.svs
    └── cd8/ case01_CD8.svs case02_CD8.svs
```

```python
import rocqipath as rp

result = rp.align("pairs/", "aligned/", reference_name="he", moving_name="cd8", qc_enabled=True)

# Two slides directly, reference first:
rp.align(["case01_HE.svs", "case01_CD8.svs"], "aligned/", backend="orb")

# Backend settings are nested:
rp.align("pairs/", "aligned/", valis__max_acceptable_error_um=100)
```

```console
rocqipath align pairs/ aligned/ --reference-name he --moving-name cd8 --qc-enabled
rocqipath align pairs/ aligned/ --backend orb --orb.ransac-threshold 10
rocqipath align pairs/ aligned/ --dry-run          # check pairing without registering
```

- **`valis`** (default) handles local tissue deformation, and needs the
  `valis` extra.
- **`orb`** is a fast global affine registration, and needs the `orb` extra.

## Reference

::: rocqipath.api.align

::: rocqipath.alignment.config.AlignConfig

::: rocqipath.alignment.config.ValisOptions

::: rocqipath.alignment.config.OrbOptions
