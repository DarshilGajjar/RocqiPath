# Coordinates and canvases

Three coordinate systems are in play whenever RocqiPath reads a slide, and
mixing them up is the most common source of subtly misaligned output.

## The three systems

**Level-0 coordinates** are the slide's native full-resolution pixel grid. This
is what OpenSlide's `read_region` expects for its location argument, regardless
of which level you are reading.

**Native-level coordinates** belong to whichever pyramid level was actually
read. They are level-0 coordinates divided by that level's downsample factor.

**Target-grid coordinates** are RocqiPath's working system: the pixel grid at
the physical magnification you asked for. All public APIs speak this language.

## The contract

`SlideReader.read_at_magnification(location, size)` takes **target-grid**
values for both arguments. It converts to level-0 internally, selects the
native level, reads, and resizes once to land on the exact requested zoom.

```python
from rocqipath.core.slide import SlideReader

with SlideReader("/mnt/archive/demo/CASE-001_he.svs") as reader:
    reader.configure_magnification(target_magnification=20.0)
    tile = reader.read_at_magnification((4096, 2048), (512, 512))
    # 512x512 pixels at exactly 20x, whatever the scanner did.
```

You never pass a level number. That is the whole point — see
[magnification, not pyramid levels](magnification.md).

## Canvas agreement in paired work

Paired patch extraction reads the same target-grid coordinates from two
different slides and expects the results to correspond. That only holds if both
slides describe the same physical field of view at the same zoom.

RocqiPath checks this rather than assuming it. Reference and moving canvases
are compared at the target magnification, and a mismatch beyond
`dimension_tolerance` (1% by default) is an error, not a silent crop.

The check matters because the two slides may have been scanned on different
machines at different objectives, and because registration output has its own
canvas convention. A 1% disagreement at 20x across a 40 mm section is roughly
200 micrometres — enough to shift a patch into neighbouring tissue.

## Where each system appears on disk

| Artifact | Coordinate system |
| --- | --- |
| Region manifests (`coordinates.absolute_pixels`) | level 0 |
| Patch manifest `x0`, `y0` | level 0 |
| Patch `size`, `stride` | target grid |
| Alignment transforms | as produced by the backend, recorded with its own reference |

Storing patch positions in level-0 coordinates is deliberate: they stay valid
if you later re-extract the same regions at a different magnification, which
target-grid coordinates would not.
