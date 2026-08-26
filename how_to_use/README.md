# RocqiPath how-to-use notebooks

These notebooks are the practical documentation for RocqiPath. They call the
feature APIs directly without a dataset or experiment-management layer.

## Recommended order

| Notebook | Purpose | Install extra |
|---|---|---|
| `00_Installation_and_API_Overview.ipynb` | Environment, imports, typed configs, output layout | base |
| `01_Slide_Inspection_and_Magnification.ipynb` | Open a slide and read exact physical magnification | `extraction` |
| `02_WSI_and_TMA_Tissue_Extraction.ipynb` | Ordinary WSI regions and TMA/core extraction | `extraction` |
| `03_HnE_IHC_Alignment.ipynb` | Pair discovery, dry run, ORB/VALIS registration, QC | `orb` or `valis` |
| `04_Paired_Patch_Extraction_and_Reconstruction.ipynb` | Matched patches, manifests, viewing, reconstruction | `extraction,viz` |
| `05_Stain_Normalization.ipynb` | Train and apply Reinhard/Macenko/Vahadane normalization | `stain` |
| `06_DAB_Positive_Cell_Counting.ipynb` | Single, batch, and paired DAB-positive cell counts | `cellcount` |
| `07_Visualization_and_Quality_Control.ipynb` | Patch QC, grid maps, marker overlays, publication figures | `viz` |
| `08_End_to_End_HnE_CD8_Workflow.ipynb` | Direct H&E/CD8 alignment-to-analysis workflow | combined extras |

## Start Jupyter

RocqiPath supports 64-bit Python 3.10–3.11. From the repository root:

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[extraction,orb,stain,cellcount,viz]"
python -m pip install jupyterlab
jupyter lab
```

Use `.[valis]` instead of or in addition to `.[orb]` when VALIS registration
is required. OpenSlide and libvips are native prerequisites for WSI workflows;
installing the Python packages alone may not install those runtimes.

## Notebook conventions

- Edit the clearly marked **Parameters** cell first.
- Long-running cells use a `RUN_*` switch and default to `False`.
- Physical zoom is always an objective magnification such as `20.0`, never a
  scanner pyramid level.
- Plain TIFF files without objective metadata need an explicit
  `source_magnification`.
- Outputs follow `<results>/<module>/<slide-or-case>/`.
- The alignment-to-patch handoff notebook includes a staging helper because
  alignment output and the current patch resolver use different directory
  contracts. The helper copies or hard-links files; it does not alter originals.

## Validation

The notebooks were checked against the current public APIs on 2026-08-25.
Data-dependent and long-running cells remain disabled by default.
