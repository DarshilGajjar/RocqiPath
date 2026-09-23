# Configs

Every workflow's settings are a dataclass. Build one directly, derive one
with `replace`, load one from TOML, or pass fields as keywords to the
workflow.

```python
cfg = rp.AlignConfig(backend="orb", qc_enabled=True)
cfg = cfg.replace(target_magnification=10, orb__ransac_threshold=12)
cfg = rp.AlignConfig.from_toml("align.toml")
rp.align("pairs/", "aligned/", config=cfg)
```

Each config is documented field by field on its workflow's page:

| Config | Workflow page |
|---|---|
| `ExtractTissueConfig` | [Extract tissue](../workflows/extract-tissue.md) |
| `ExtractTMAConfig` | [Extract TMA cores](../workflows/extract-tma.md) |
| `ExtractPatchesConfig` | [Extract patch pairs](../workflows/extract-patches.md) |
| `AlignConfig`, `ValisOptions`, `OrbOptions` | [Align slides](../workflows/align.md) |
| `StainConfig` | [Stain normalization](../workflows/stain.md) |
| `CountCellsConfig` | [Count cells](../workflows/count-cells.md) |
| `CompareConfig` | [Comparison figures](../workflows/compare.md) |
| `OverlayConfig`, `MarkerProfile`, `OverlayCombo` | [Marker overlays](../workflows/overlay-markers.md) |

## Shared behavior

::: rocqipath._internal.base_config.BaseConfig
