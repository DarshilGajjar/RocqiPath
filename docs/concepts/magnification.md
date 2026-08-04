# Magnification, not pyramid levels

> A pyramid level is not a magnification. This is the single most consequential
> design decision in RocqiPath, and the one most likely to silently corrupt
> results in code that gets it wrong.

## The problem

A whole-slide image is stored as a pyramid: level 0 at full resolution, then
successively downsampled copies. It is tempting to treat the level number as a
zoom setting — `level=1` for "half resolution", and so on.

It does not mean that. What level 1 represents depends on the scanner:

| Scanner | Level 0 | Level 1 | Level 2 |
| --- | --- | --- | --- |
| 40x whole-section scan, 2x steps | 40x | 20x | 10x |
| 80x TMA scan, 2x steps | 80x | 40x | 20x |
| 20x scan, 4x steps | 20x | 5x | 1.25x |

Ask three of those scanners for "level 1" and you get 20x, 40x, and 5x. Patches
extracted that way are not comparable, and nothing in the file format will tell
you. A model trained on the mixture learns scanner identity as a confounder.

The failure is silent. That is what makes it dangerous.

## What RocqiPath does instead

You ask for a physical objective magnification:

```toml
default_magnification = 20.0
```

For each slide, independently, RocqiPath then:

1. reads the level-0 objective magnification from OpenSlide or libvips metadata;
2. finds the native pyramid level closest to the requested physical zoom, using
   log-distance so that 10x-versus-20x counts as far as 20x-versus-40x;
3. maps target-grid coordinates back to level-0 coordinates;
4. reads enough pixels from that native level;
5. resizes once, only if needed, to land on the exact requested zoom.

Reference and moving slides are resolved separately. An 80x reference and a 40x
moving slide both produce spatially comparable 20x patches, because the
question asked of each was "give me 20x", not "give me level 1".

## Two rules that follow

**Upsampling is refused, not performed.** Requesting 40x output from a 20x scan
raises an error. RocqiPath will not invent resolution that the microscope never
captured, and it will not let a cohort quietly contain interpolated pixels
labelled as if they were real.

**Missing metadata is an error, not a guess.** Plain TIFFs often carry no
objective-power tag. Rather than assume, RocqiPath asks:

```toml
[overrides."TMA12-A3__he__s01"]
source_magnification = 80.0
note = "Scanner wrote no objective-power tag."
```

Per slide, in one place, versioned with the study and annotated with a reason.
A cohort that mixes an 80x TMA scanner with a 40x whole-section scanner is
handled correctly, which a single global setting cannot do.

`rocqipath study survey` finds every slide with this problem in one pass, and
`rocqipath study verify` refuses to run until each is resolved.

## Provenance

TIFFs written by RocqiPath carry a sibling JSON manifest containing
`output_magnification`. Downstream RocqiPath readers pick it up automatically,
so a derived image never loses track of what zoom it represents.

## In the API

```python
from rocqipath.core.magnification import build_magnification_plan

plan = build_magnification_plan(
    base_magnification=80.0,        # what the scanner recorded
    target_magnification=20.0,      # what you asked for
    level_downsamples=(1.0, 4.0, 16.0),
)

plan.level              # native level chosen
plan.resize_factor      # final exact-scale correction
plan.target_to_level0((0, 0))   # output grid -> level-0 coordinates
```

## See also

- [Coordinates and canvases](coordinates-and-canvases.md)
- [`study.toml` reference](../reference/study-toml.md)
