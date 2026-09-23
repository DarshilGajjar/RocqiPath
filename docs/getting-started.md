# Getting started

## Install

RocqiPath supports 64-bit Python 3.10 and 3.11. Install only the parts you
need. Each workflow names the *extra* it requires:

```console
git clone https://github.com/DarshilGajjar/RocqiPath.git
cd RocqiPath
python -m pip install -e ".[extraction,orb,stain,cellcount,viz]"
```

| Extra | Enables |
|---|---|
| `extraction` | `extract_tissue`, `extract_tma`, `extract_patches` |
| `semantic` | the TIAToolbox tissue model (`detector="semantic"`) |
| `orb` | `align` with the lightweight ORB backend |
| `valis` | `align` with VALIS (rigid and non-rigid, the default backend) |
| `stain` | `train_stain_normalizer`, `normalize_stain` |
| `cellcount` | `count_cells` |
| `viz` | `compare`, `overlay_markers` and plotting helpers |
| `studio` | the local browser workspace |

Slide reading uses **OpenSlide** and writing pyramids uses **libvips**. Both
are native libraries. If your system does not provide them, pip-installable
builds work too:

```console
python -m pip install openslide-bin "pyvips[binary]"
```

`rocqipath list` shows which workflows are ready in your environment.

## First run in Python

```python
import rocqipath as rp

result = rp.extract_tissue(
    "slides/",               # a folder of .svs / .ndpi / .tif slides
    "results/",
    target_magnification=10, # save regions at 10x
)

for item in result.by_role("region"):
    print(item.sample_id, item.path, item.meta["absolute_box"])
```

- **Unknown settings:** a mistyped setting raises an error that suggests the
  closest name.
- **Settings reference:** every setting is listed on the config class; see
  `help(rp.ExtractTissueConfig)` or the [reference](reference/configs.md).
- **Plain TIFFs:** files without objective metadata need
  `source_magnification`. See [Magnification](concepts/magnification.md).

## First run on the command line

Every workflow is also a command with one flag per setting:

```console
rocqipath extract-tissue slides/ regions/ --target-magnification 10
rocqipath align pairs/ aligned/ --backend orb --qc-enabled
rocqipath count-cells aligned/ counts/ --label CD8     # counts the aligned slides
```

- `--help` shows the common settings, and `--help-all` shows every one.
- `--config settings.toml` loads saved settings.

## First run in Studio

```console
python -m pip install -e ".[studio,extraction,cellcount]"
rocqipath studio
```

Then open <http://127.0.0.1:8765>. See [Studio](studio.md).

## Notebooks

The [`how_to_use`](https://github.com/DarshilGajjar/RocqiPath/tree/main/how_to_use)
notebooks walk through each workflow with editable parameters and switches
that keep long steps off until you enable them.
