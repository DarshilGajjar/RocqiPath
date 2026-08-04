# `study.toml` reference

The cohort descriptor. The only file in a study you write by hand; everything
else under the study directory is generated and safe to delete and rebuild.

Create a commented starting point with:

```console
$ rocqipath study init mystudy --source /mnt/archive/crc_2024 --stain he --stain cd8
```

## Top level

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | *(required)* | Study name. |
| `description` | string | — | Free text carried into generated reports. |
| `default_magnification` | float | `20.0` | Physical output objective magnification. Never a pyramid level. |
| `detection_magnification` | float | `1.25` | Coarse zoom used for tissue and core detection. |
| `patch_size` | int | `512` | Paired-patch edge length, in target-grid pixels. |
| `stride` | int | `patch_size` | Patch grid step. Values below `patch_size` overlap. |
| `alignment_method` | `"valis"` \| `"orb"` | `"valis"` | Registration backend. |
| `normalizer` | `"reinhard"` \| `"macenko"` \| `"vahadane"` | `"macenko"` | Stain normalisation method. |

## `[[sources]]`

Where slides live. Repeat the table for multiple archives. Roots are **read
only**: RocqiPath references slides in place and never copies or renames them.

```toml
[[sources]]
root = "/mnt/archive/crc_2024"
pattern = '(?P<case>.+?)_(?P<stain>he|cd8|cd31)(?:_s(?P<section>\d+))?\.(svs|ndpi|tif)$'
recursive = true
```

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `root` | path | *(required)* | Directory searched for slides. |
| `pattern` | regex | see below | Decodes each filename into identity. |
| `recursive` | bool | `true` | Search sub-directories. |

The pattern **must** capture `case` and `stain`, and **may** capture `section`.
Matching is case-insensitive and applied to the filename only, not the full
path. Use single-quoted TOML strings so backslashes stay literal.

Together the groups form the `slide_uid`:

```
<case>__<stain>__s<NN>          e.g.  BLOCK_12_A__cd8__s03
```

A double underscore separates fields so case identifiers may contain single
underscores. `section` defaults to `1` when the group is absent.

Files that do not match are reported as warnings by `rocqipath study index`,
never silently dropped.

## `[stains.<key>]`

One table per stain or biomarker. The key is the lowercase value the `stain`
group captures.

```toml
[stains.he]
role = "reference"

[stains.cd8]
role = "moving"
chromogen = "dab"
display_name = "CD8+ T cells"
```

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `role` | `"reference"` \| `"moving"` | `"moving"` | Reference slides are registration targets; moving slides are warped onto them. |
| `chromogen` | string | — | For example `"dab"`. Drives which slides the counting stage acts on. |
| `display_name` | string | — | Label used in figures and result tables. |
| `source_magnification` | float | — | Fallback objective magnification for every slide of this stain. |

**Exactly one stain must carry `role = "reference"`.** Pairs are then derived
as case × (reference, moving), so a single H&E serves every biomarker in the
cohort without being duplicated on disk.

## `[overrides."<slide_uid>"]`

Per-slide corrections that cannot be expressed cohort-wide. The key is a full
`slide_uid`, quoted.

```toml
[overrides."TMA12-A3__he__s01"]
source_magnification = 80.0
note = "Scanner wrote no objective-power tag."

[overrides."TMA12-B7__cd8__s01"]
exclude = true
note = "Coverslip damage across the core."
```

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `source_magnification` | float | — | Level-0 objective magnification for a slide whose scanner wrote none. |
| `exclude` | bool | `false` | Drop the slide from the study entirely. |
| `note` | string | — | Why the override exists. Write one; your future self will want it. |

This is the right home for magnification fallbacks. A cohort mixing an 80x TMA
scanner with a 40x whole-section scanner is handled correctly here, which a
single global setting cannot do.

## Validation

```console
$ rocqipath study verify mystudy
```

Checks the descriptor for structural problems — no sources, two reference
stains, a pattern missing a required group, a detection magnification above the
output magnification — alongside index and survey checks. Every error names the
edit that resolves it.

## Complete example

```toml
name = "colorectal_cd8"
description = "CRC cohort, CD8 and CD31 on serial sections."
default_magnification = 20.0
detection_magnification = 1.25
patch_size = 512
alignment_method = "valis"
normalizer = "macenko"

[[sources]]
root = "/mnt/archive/crc_2024"
pattern = '(?P<case>.+?)_(?P<stain>he|cd8|cd31)(?:_s(?P<section>\d+))?\.(svs|ndpi|tif)$'
recursive = true

[stains.he]
role = "reference"

[stains.cd8]
role = "moving"
chromogen = "dab"

[stains.cd31]
role = "moving"
chromogen = "dab"

[overrides."CRC-118__he__s01"]
source_magnification = 40.0
note = "Re-scan on the legacy machine; no objective tag."
```
