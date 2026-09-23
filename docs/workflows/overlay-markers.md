# Marker overlays

Turns several IHC markers into colored masks and layers them over a base
marker to show co-localization. Each case folder has one subfolder of patches
per marker, with the same filenames in each.

```python
import rocqipath as rp

rp.overlay_markers(
    "case01/",
    "figures/",
    markers={
        "he": rp.MarkerProfile(color=(0, 0, 255)),
        "cd8": rp.MarkerProfile(color=(255, 0, 0)),
        "cd4": rp.MarkerProfile(color=(0, 180, 0), hue_range=(5, 20)),
    },
    combinations=[rp.OverlayCombo(base="he", overlays=["cd8", "cd4"])],
    base_marker="he",
)
```

On the command line, markers and combinations are JSON (or use a TOML
`--config` file):

```console
rocqipath overlay-markers case01/ figures/ --base-marker he \
  --markers '{"he": {"color": [0,0,255]}, "cd8": {"color": [255,0,0]}}' \
  --combinations '[{"base": "he", "overlays": ["cd8"]}]'
```

## Reference

::: rocqipath.api.overlay_markers

::: rocqipath.viz.config.OverlayConfig

::: rocqipath.viz.config.MarkerProfile

::: rocqipath.viz.config.OverlayCombo
