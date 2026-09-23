# Outputs and manifests

## Where results go

Each workflow writes beneath the `output_dir` you give it, in a folder named
after the module, with one subfolder per slide or case:

```text
results/
├── rocqipath.json                 # what this folder contains (below)
└── tissue_extraction/
    └── slideA/
        ├── region_001.tif         # pyramidal TIFF at target_magnification
        ├── region_001_preview.jpg
        ├── region_001_manifest.json
        └── slideA_manifest.json
```

The per-region and per-slide manifests record provenance: source file, boxes
in relative and absolute pixels, magnifications and detector. Aligned slides
carry a `*_manifest.json` recording their magnification, which later
workflows read automatically.

## The run manifest: `rocqipath.json`

After every successful run, the workflow records what it did in
`output_dir/rocqipath.json`:

```json
{
  "schema": 1,
  "runs": {
    "align": {
      "rocqipath_version": "2.0.0",
      "created": "2026-09-23T10:00:00Z",
      "config": {"backend": "orb", "target_magnification": 20.0, "...": "..."},
      "inputs": ["/data/pairs"],
      "summary": {"cases": ["..."]},
      "items": [
        {"sample_id": "case01", "role": "reference", "path": "/data/pairs/CD8/he/case01_HE.tif", "...": "..."},
        {"sample_id": "case01", "role": "aligned",
         "path": "alignment/case01_cd8/case01_cd8_aligned_moving.ome.tiff", "...": "..."}
      ]
    }
  }
}
```

- **Relative paths:** paths inside the folder are stored relative to it, so
  results can be moved or copied.
- **Shared folders:** several workflows may write into one folder. Each keeps
  its latest run under its own name.
- **Failed runs** write nothing, so a half-finished folder is never mistaken
  for a result.
- **Provenance:** the exact settings are recorded under `config`, so any run
  can be repeated.

## `Result` and `Item`

In Python, every workflow returns a [`Result`](../reference/results.md):

```python
result = rp.align("pairs/", "aligned/")
result.output_dir          # Path to aligned/
result.summary             # workflow-specific numbers
result.config              # the AlignConfig used
for item in result.by_role("aligned"):
    print(item.sample_id, item.path, item.magnification, item.meta)
```

An `Item` is one produced file. Its `role` says what it is:

| Role | Produced by |
|---|---|
| `region` | `extract_tissue` |
| `core` | `extract_tma` |
| `reference`, `aligned`, `figure` | `align` |
| `patch` (with `meta["stain"]`) | `extract_patches` |
| `weights` | `train_stain_normalizer` |
| `normalized` | `normalize_stain` |
| `count`, `figure` | `count_cells` |
| `figure` | `compare`, `overlay_markers` |

`rocqipath.io.manifest.read_run_manifest(folder)` reads a folder back into
`Result` objects.
