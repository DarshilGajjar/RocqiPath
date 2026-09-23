# How to use RocqiPath — notebooks

Practical, editable walkthroughs of every workflow. Each notebook starts with
a **Parameters** cell; long-running steps sit behind `RUN_*` switches that
default to `False`, and small synthetic examples run straight away without
any private data.

| Notebook | Purpose | Extras |
|---|---|---|
| `00_Installation_and_API_Overview` | Environment check, the one calling pattern, settings, results | base |
| `01_Slide_Inspection_and_Magnification` | Open slides, resolve magnification, read exact regions | `extraction` |
| `02_WSI_and_TMA_Tissue_Extraction` | `rp.extract_tissue` and `rp.extract_tma` | `extraction` |
| `03_HnE_IHC_Alignment` | Pairing, dry run, ORB/VALIS alignment, QC | `orb` or `valis` |
| `04_Paired_Patch_Extraction_and_Reconstruction` | Matched patches straight from alignment; reconstruction | `extraction,viz` |
| `05_Stain_Normalization` | Train and apply Reinhard/Macenko/Vahadane | `stain` |
| `06_DAB_Positive_Cell_Counting` | Single, cohort and real-vs-predicted counting | `cellcount` |
| `07_Visualization_and_Quality_Control` | Patch QC, grid maps, marker overlays, comparison figures | `viz` |
| `08_End_to_End_HnE_CD8_Workflow` | Alignment → patches → normalization → counts, chained | combined |

## Start Jupyter

From the repository root, with Python 3.10 or 3.11:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[extraction,orb,stain,cellcount,viz]"
python -m pip install jupyterlab
jupyter lab
```

Put your slides under `data/` and results go to `results/`; both are ignored
by git. Synthetic examples write to `notebook_demo_outputs/`.

The full documentation, including every setting of every workflow, is in
[`docs/`](../docs/index.md) (build it with `mkdocs serve`).
