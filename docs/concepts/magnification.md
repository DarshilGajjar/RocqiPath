# Magnification

RocqiPath always talks about **objective magnification**: `20.0` means
"as if scanned with a 20x objective". Every workflow that reads slides takes
a `target_magnification` and resamples to it exactly, whichever pyramid level
the scanner happened to store.

- **Pyramid levels are not magnifications.** Level 1 of one scanner may be
  10x and of another 5x. RocqiPath reads the stored level closest to the
  target and resizes the rest of the way, so coordinates and patch sizes mean
  the same thing on every slide. A target above the scan magnification is
  refused, because upsampling cannot add detail.
- **Patch sizes are in target pixels.** `patch_size=512` at
  `target_magnification=20` covers the same tissue as `patch_size=256` at 10x.

## How the scan magnification is found

To resample, RocqiPath needs the slide's own (level-0) magnification. It
checks, in order:

1. **An explicit `source_magnification`** you pass (for alignment:
   `reference_source_magnification` and `moving_source_magnification`).
2. **Scanner metadata**: `openslide.objective-power`, `aperio.AppMag` or
   `hamamatsu.SourceLens`.
3. **A RocqiPath manifest next to the file.** Slides written by `rp.align`
   record their magnification this way, so later workflows need no setting.

If none is available the workflow stops with an error rather than silently
working at the wrong scale.

!!! tip "Plain TIFF files"
    Ordinary TIFFs and PNGs carry no objective metadata. Pass
    `source_magnification=` with the objective they were scanned at.
    `rocqipath info SLIDE` shows what a file reports.

## Detection magnification

Tissue detection runs on a small thumbnail at `detection_magnification`
(default 1.25x) for speed. Region boxes are then scaled up and cut at
`target_magnification`. `detection_magnification` may not exceed
`target_magnification`.
