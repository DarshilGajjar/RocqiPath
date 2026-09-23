![RocqiPath pathology image-analysis workflow](assets/rocqipath-banner.png)

# RocqiPath

Whole-slide image processing for computational pathology: cut out tissue
and TMA cores, align IHC slides onto H&E, extract matched patch pairs,
normalize stains, count DAB-positive cells, and make QC and publication
figures.

```python
import rocqipath as rp

aligned = rp.align("pairs/", "results/aligned", backend="orb")
patches = rp.extract_patches(aligned, "results/patches", patch_size=512)
counts = rp.count_cells(aligned, "results/counts", label="CD8")
```

Every workflow is called the same way, `rp.<workflow>(inputs, output_dir, **settings)`,
and returns a `Result` listing the files it produced. A workflow's result, or
its output folder, can be the next workflow's input.

| Workflow | Command | What it does |
|---|---|---|
| `rp.extract_tissue` | `rocqipath extract-tissue` | Cut each piece of tissue out of whole-slide images |
| `rp.extract_tma` | `rocqipath extract-tma` | Cut TMA cores out of H&E and matching IHC slides |
| `rp.align` | `rocqipath align` | Register IHC slides onto H&E (VALIS or ORB) |
| `rp.extract_patches` | `rocqipath extract-patches` | Pixel-matched H&E/IHC patch pairs |
| `rp.train_stain_normalizer`, `rp.normalize_stain` | `rocqipath train-stain-normalizer`, `normalize-stain` | Reinhard, Macenko or Vahadane |
| `rp.count_cells` | `rocqipath count-cells` | DAB-positive cell counts and density, or real-vs-predicted comparison |
| `rp.compare` | `rocqipath compare` | H&E / true IHC / predicted IHC figures |
| `rp.overlay_markers` | `rocqipath overlay-markers` | Several IHC markers as colored masks |

## Install

RocqiPath supports 64-bit Python 3.10 and 3.11. Install the extras for the
workflows you use:

```console
git clone https://github.com/DarshilGajjar/RocqiPath.git
cd RocqiPath
python -m pip install -e ".[extraction,orb,stain,cellcount,viz]"
```

Use `valis` instead of (or with) `orb` for non-rigid alignment, `semantic` for
the TIAToolbox tissue model, and `studio` for the browser workspace. OpenSlide
and libvips are native libraries; `python -m pip install openslide-bin "pyvips[binary]"`
installs both if your system does not. `rocqipath list` shows what is ready.

## Use

- **Python** — `import rocqipath as rp`; every setting is a documented field of
  the workflow's config class (`help(rp.AlignConfig)`).
- **Command line** — `rocqipath <workflow> INPUT… OUTPUT --setting value`;
  `--help` for common settings, `--help-all` for every one, `--config file.toml`.
- **Studio** — `rocqipath studio`, then open <http://127.0.0.1:8765>: a local
  slide library, viewer, workflow forms and job history.
- **Notebooks** — [`how_to_use/`](how_to_use/README.md) walks through every workflow.

## Documentation

The [docs](docs/index.md) cover getting started, the concepts every workflow
shares (magnification, output manifests, chaining), each workflow with its
full settings reference, Studio, and contributing. Build them locally with:

```console
python -m pip install -e ".[docs]"
mkdocs serve
```

Upgrading from 1.x? See [MIGRATION.md](MIGRATION.md).

## Development

```console
python -m pip install -e ".[test]"
python -m pytest
ruff check src tests
```

The suite runs every workflow on small synthetic slides and compares the
outputs against recorded snapshots (`tests/golden`), so refactoring cannot
silently change results. See [Contributing](docs/contributing/architecture.md)
for the architecture and how to add a workflow.

## Safety

Whole-slide images and filenames may contain patient information. Keep data
outside the repository and do not attach it to public issues.

## License

No license has been selected yet. See [LICENSE](LICENSE) for the current terms.
