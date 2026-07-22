# RocqiPath

RocqiPath is a modular Python library for whole-slide image processing in
computational pathology. It provides slide alignment, WSI and TMA tissue
extraction, paired patch extraction, stain normalization, DAB-positive cell
counting, and visual quality-control tools through typed Python APIs and a CLI.

The package uses physical objective magnification throughout. The default is
**20x**, regardless of whether the source slide was scanned at 20x, 40x, or
80x. A scanner pyramid level is never treated as a magnification.

> Status: private research software. See [LICENSE](LICENSE).

## Installation

RocqiPath is tested with 64-bit Python 3.10â€“3.11. Python 3.11 (64-bit) is
recommended for the complete installation because the current TIAToolbox/Numba
dependency stack does not support Python 3.12 or newer.

```bash
git clone https://github.com/DarshilGajjar/RocqiPath.git
cd RocqiPath

# Lightweight installation: CLI, logging, and shared utilities
python -m pip install -e .

# Install only the capabilities required by your workflow
python -m pip install -e ".[extraction]"
python -m pip install -e ".[valis]"
python -m pip install -e ".[stain]"
python -m pip install -e ".[cellcount]"
python -m pip install -e ".[viz]"
```

Extras can be combined, for example
`python -m pip install -e ".[extraction,cellcount,viz]"`.

### Additional VALIS prerequisite: libvips

RocqiPathâ€™s alignment and pyramidal-image workflows use `pyvips`, which requires the native **libvips** runtime. Installing `valis-wsi` with `pip` installs the Python packages, but does not install libvips on Windows.

#### Windows installation

1. Download the 64-bit Windows libvips binary from the [official libvips installation page](https://www.libvips.org/install.html).
2. Extract it to a permanent location, for example `C:\tools\vips`.
3. Add the extracted `bin` directory (for example, `C:\tools\vips\bin`) to your Windows **User PATH** environment variable.
4. Close and reopen PowerShell, then activate your RocqiPath environment:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m pip install -e ".[valis]"
   ```

## Standard output layout

Every main pipeline receives one general output root and writes to:

```text
<output_root>/
â”œâ”€â”€ alignment/
â”‚   â””â”€â”€ <case_name>/
â”œâ”€â”€ tissue_extraction/
â”‚   â””â”€â”€ <input_slide_name>/
â”œâ”€â”€ patch_extraction/
â”‚   â””â”€â”€ <case_name>/
â”œâ”€â”€ stain_normalization/
â”‚   â””â”€â”€ <input_file_name>/
â””â”€â”€ cell_counting/
    â””â”€â”€ <input_or_pair_name>/
```

All outputs for one slide or case are stored together. Region, stain, grid,
patch-size, and channel information is encoded in filenames and manifests; the
pipelines do not create a deep directory tree for those attributes.

## Magnification model

Use `target_magnification`, not a numeric pyramid level:

```python
target_magnification = 20.0  # default
```

For each slide RocqiPath:

1. reads the level-0 objective magnification from OpenSlide/libvips metadata;
2. finds the native pyramid level closest to the requested physical zoom;
3. maps target-grid coordinates back to level-0 coordinates;
4. reads enough pixels from that native level; and
5. resizes once, if necessary, to return the exact requested zoom.

Reference and moving slides are resolved independently, so an 80x reference
and a 40x moving slide can both produce spatially comparable 20x patches.

If a plain TIFF has no objective metadata, set a scanner-specific fallback:

```python
source_magnification = 80.0
```

TIFFs created by RocqiPath also have a sibling JSON manifest containing
`output_magnification`; downstream RocqiPath readers use it automatically.
Requests above the source objective (for example, 40x output from a 20x scan)
are rejected rather than silently inventing resolution.

## Tissue extraction

WSI and TMA/core workflows are separate public entry points, avoiding config
collisions while sharing detection, magnification, TIFF writing, manifests,
logging, and output rules.

### Ordinary WSI sections

```python
from rocqipath.extraction import TissueExtractionConfig, run_tissue_pipeline

cfg = TissueExtractionConfig(
    target_magnification=20.0,
    detection_magnification=1.25,
    min_area_fraction=0.005,
)

results = run_tissue_pipeline(
    input_dir="./data/wsi",
    output_dir="./results",
    cfg=cfg,
)
```

Output example:

```text
results/tissue_extraction/slide_01/
â”œâ”€â”€ region_001.tif
â”œâ”€â”€ region_001_preview.jpg
â”œâ”€â”€ region_001_manifest.json
â””â”€â”€ slide_01_manifest.json
```

### 80x TMA/core slides

```python
from rocqipath.extraction import CoreExtractionConfig, run_core_extraction_pipeline

cfg = CoreExtractionConfig(
    target_magnification=20.0,
    detection_magnification=1.25,
    source_magnification=80.0,  # omit when correct metadata is present
    only_circles=True,
    min_circularity=0.60,
    per_stain_detection=True,
    fallback_to_he=True,
)

run_core_extraction_pipeline(
    input_dir="./data/tma",
    output_root="./results",
    cfg=cfg,
    target_stains=["H&E", "CD8", "CD31"],
)
```

Explicit `target_stains` also allows custom biomarker names that are not in the
built-in convenience keyword list.

## Paired patch extraction

```python
from rocqipath.extraction import PatchExtractionConfig, run_patch_extraction

summary = run_patch_extraction(PatchExtractionConfig(
    he_dir="./data/reference",
    aligned_dir="./results/alignment",
    output_dir="./results",
    biomarker_folders=["CD8"],
    he_filename_pattern=r"^(?P<sample_id>.+?)_he\.tiff?$",
    he_channel_name="he",
    ihc_channel_name="cd8",
    patch_size=512,
    stride=512,
    tissue_threshold=0.50,
    target_magnification=20.0,
    max_workers=4,
))
```

The pipeline validates that the reference and moving canvases agree at 20x,
uses the same target-grid coordinates for both channels, and records the base
magnification and native read level for each slide in the case manifest.

## Alignment

```python
from rocqipath.registration import AlignmentConfig, run_alignment

results = run_alignment(AlignmentConfig(
    input_dir="./data/pairs",
    output_dir="./results",
    alignment_method="valis",  # or "orb"
    target_magnification=20.0,
    qc_enabled=True,
))
```

Expected input:

```text
data/pairs/<biomarker>/he/<sample>_he.<ext>
data/pairs/<biomarker>/ihc/<sample>_<biomarker>.<ext>
```

## Stain normalization and cell counting

```python
from rocqipath.stain import (
    StainNormalizationConfig,
    run_stain_normalization_apply,
    run_stain_normalization_train,
)

cfg = StainNormalizationConfig(n_type="macenko", stains=["he"])
run_stain_normalization_train("./patches", "./results", cfg)
run_stain_normalization_apply("./patches", "./results", cfg)
```

```python
from rocqipath.analysis import PositiveCellCounter

counter = PositiveCellCounter({
    "output_dir": "./results",
    "target_magnification": 20.0,
    "patch_size": 512,
})
counter.count_slide("./data/cd8.svs", label="CD8")
```

## Public package layout

```text
src/rocqipath/
â”œâ”€â”€ magnification.py       # objective metadata and pyramid-level plans
â”œâ”€â”€ slide.py               # shared OpenSlide/PIL reader
â”œâ”€â”€ output.py              # <root>/<module>/<item> layout
â”œâ”€â”€ exceptions.py          # common exception hierarchy
â”œâ”€â”€ logger.py              # Rich/loguru output helpers
â”œâ”€â”€ registration/          # VALIS/ORB alignment
â”œâ”€â”€ extraction/            # WSI, TMA/core, and paired patches
â”œâ”€â”€ stain/                 # Reinhard, Macenko, Vahadane
â”œâ”€â”€ analysis/              # positive-cell counting
â””â”€â”€ visualization/         # grids, paired QC, IHC overlays, comparisons
```

Primary symbols are re-exported from each subpackage. Import private helpers
whose names start with `_` only when extending RocqiPath itself.

## CLI

```bash
rocqipath
```

The menu separates ordinary WSI tissue extraction from TMA/core extraction and
prompts for physical output magnification. For reproducible research pipelines,
the typed Python APIs are preferred because configurations can be versioned.

## Development

```bash
python -m pip install -e .
python -m pip install "pillow>=10.0" "pytest>=7.4" "ruff>=0.4"
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
```

Development tools are intentionally installed separately and are not package
runtime dependencies. GitHub Actions runs the lightweight unit suite on Python
3.10 and 3.11. Integration
tests requiring scanner files and native WSI libraries should be marked and run
in an environment that provides those assets.

See [CONTRIBUTING.md](CONTRIBUTING.md) before adding a module or public API.

## Software citations

When RocqiPath contributes to published research, cite RocqiPath and cite the underlying software components that were materially used in the reported analysis. You do not need to cite every utility dependency for every project.

- **VALIS** â€” cite when using WSI registration or alignment:

  Gatenbee, C. D., Baker, A.-M., Prabhakaran, S., Robertson-Tessi, M., Graham, T. A., & Anderson, A. R. A. (2023). _Virtual alignment of pathology image series for multi-gigapixel whole slide images_. Nature Communications, 14, 4062. https://doi.org/10.1038/s41467-023-40218-9

- **TIAToolbox** â€” cite when using TIAToolbox-based stain normalization or tissue-image analysis:

  Pocock, J., Graham, S., Vu, Q. D., et al. (2022). _TIAToolbox as an end-to-end library for advanced tissue image analytics_. Communications Medicine, 2, 120. https://doi.org/10.1038/s43856-022-00186-5

- **scikit-image** â€” cite when using tissue masking, segmentation, morphology, or related image-processing operations:

  van der Walt, S., SchÃ¶nberger, J. L., Nunez-Iglesias, J., et al. (2014). _scikit-image: Image processing in Python_. PeerJ, 2, e453. https://doi.org/10.7717/peerj.453

- **NumPy** â€” cite when numerical array processing is a substantive part of the analysis:

  Harris, C. R., Millman, K. J., van der Walt, S. J., et al. (2020). _Array programming with NumPy_. Nature, 585, 357â€“362. https://doi.org/10.1038/s41586-020-2649-2

- **OpenSlide** â€” acknowledge when it is used to read whole-slide image formats:

  Goode, A., Gilbert, B., Harkes, J., Jukic, D., & Satyanarayanan, M. (2013). _OpenSlide: A vendor-neutral software foundation for digital pathology_. Journal of Pathology Informatics, 4, 27. https://doi.org/10.4103/2153-3539.119005

- **libvips / pyvips** â€” cite when using libvips-backed image I/O, resizing, or pyramidal TIFF generation:

  Cupitt, J., Martinez, K., Fuller, L., & Wolthuizen, K. A. (2025). _The libvips image processing library_. Proceedings of Electronic Imaging 2025, Burlingame. See the [official libvips citation guidance](https://github.com/libvips/libvips/blob/master/doc/cite.md).

Please also cite the specific RocqiPath release used in your work, including its version number and repository URL.