# RocqiPath

Personal tools for common pathology image-analysis jobs:

- align H&E and IHC whole-slide images;
- extract tissue regions, TMA cores, and paired patches;
- normalize stains;
- count DAB-positive cells; and
- make QC and comparison figures.

The repository is intentionally a collection of direct feature pipelines. It does not
manage datasets, experiments, recipes, stages, or training plans.

## Install

RocqiPath supports 64-bit Python 3.10 and 3.11.

```console
git clone https://github.com/DarshilGajjar/RocqiPath.git
cd RocqiPath
python -m pip install -e ".[extraction,orb,stain,cellcount,viz]"
```

Use the `valis` extra instead of `orb` when non-rigid VALIS registration is needed.
Slide reading also requires OpenSlide; registration and pyramidal TIFF output require
libvips.

## Use

The CLI maps directly to the five feature workflows:

```console
rocqipath align --help
rocqipath extract --help
rocqipath stain --help
rocqipath count --help
rocqipath compare --help
```

Python usage is equally direct:

```python
from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

config = TissueExtractionConfig(target_magnification=20.0)
run_tissue_pipeline("/path/to/slides", "/path/to/output", config)
```

The [`how_to_use`](how_to_use/README.md) notebooks cover installation, slide inspection,
extraction, alignment, patch reconstruction, stain normalization, cell counting,
visualization, and an end-to-end H&E/CD8 workflow.

## Safety

Whole-slide images and filenames may contain patient information. Keep data outside the
repository and do not attach it to public issues.

## License

No license has been selected yet. See [LICENSE](LICENSE) for the current terms.
