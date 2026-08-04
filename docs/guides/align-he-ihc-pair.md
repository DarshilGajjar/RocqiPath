# Align an H&E/IHC pair

**Goal:** register a moving IHC slide onto its reference H&E so both can be
sampled on the same coordinate grid.

**You need:** the `orb` or `valis` extra, plus native libvips and OpenSlide.

## With a study

Declare the roles once:

```toml
[stains.he]
role = "reference"

[stains.cd8]
role = "moving"
chromogen = "dab"
```

Then:

```console
$ rocqipath study run mystudy --stage alignment --dry-run
$ rocqipath study run mystudy --stage alignment
```

The dry run prints the pairs it derived. Check that list before committing to a
long job — a case missing its H&E shows up here rather than at hour three.

Pairs are derived, so one H&E serves CD8, CD31, and everything else in the
cohort without being duplicated on disk.

## Choosing a backend

| | `orb` | `valis` |
| --- | --- | --- |
| Transform | rigid, contour/ORB feature based | rigid and non-rigid |
| Install weight | light | heavy |
| Best for | serial sections that differ mainly by placement | tissue that has stretched, torn, or folded |
| Export | tiled, disk-backed, never allocates a level-sized array | backend-managed |

```console
$ rocqipath study plan mystudy --set alignment.method=orb
```

Start with `orb`. Move to `valis` when QC shows deformation that a rigid
transform cannot absorb.

## Without a study

```python
from rocqipath.registration import AlignmentConfig, run_alignment

run_alignment(AlignmentConfig(
    input_dir="./data/pairs",
    output_dir="./results",
    alignment_method="valis",
    target_magnification=20.0,
    qc_enabled=True,
))
```

Expected layout:

```
data/pairs/<biomarker>/he/<sample>_he.<ext>
data/pairs/<biomarker>/ihc/<sample>_<biomarker>.<ext>
```

Note that this layout needs the H&E duplicated under every biomarker folder.
For more than a couple of biomarkers, that cost is what studies exist to avoid.

Set `dry_run=True` to validate discovery and pairing on a base install, with no
image backend required.

## Checking the result

With `qc_enabled=True`, figures land in `qc/`. Look for:

- **Edges that line up.** Tissue boundaries should coincide, not merely
  overlap.
- **Internal structures**, not just the outline. A rigid fit can match the
  silhouette while shearing the interior.
- **Consistent direction of error.** Drift that grows across the slide points
  at a scale mismatch — usually a magnification problem, not a registration
  one.

If alignment is poor everywhere, check the survey first. Two slides resolved to
different physical magnifications will never register well, and no amount of
backend tuning fixes it.

## Next

- [Extract paired patches](paired-patches.md)
- [Coordinates and canvases](../concepts/coordinates-and-canvases.md)
