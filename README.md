# RocqiPath

[![CI](https://github.com/DarshilGajjar/RocqiPath/actions/workflows/ci.yml/badge.svg)](https://github.com/DarshilGajjar/RocqiPath/actions/workflows/ci.yml)
[![Python 3.10 | 3.11](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue.svg)](https://www.python.org/downloads/)
[![License: proprietary](https://img.shields.io/badge/license-proprietary-lightgrey.svg)](LICENSE)

**Whole-slide image processing for computational pathology, organised around
physical magnification and reproducible plans.**

RocqiPath aligns H&E and IHC slides, extracts tissue regions, TMA cores and
paired patches, normalises stains, counts chromogen-positive cells, and
produces the quality-control figures you need to trust the result.

---

## What it is, and what it isn't

**It is** a preprocessing and analysis library for slide-level pathology
workflows: registration, extraction, normalisation, counting, and QC — with a
typed Python API, a CLI, and a workspace model that keeps a cohort
reproducible from raw scans to a result table.

**It is not** a deep-learning framework. RocqiPath produces the data a model
trains on and analyses the data a model produces; it does not train models.

**Two decisions shape everything else.** Zoom is always a physical objective
magnification, never a pyramid-level number — an 80x TMA scan and a 40x
whole-section scan both yield comparable 20x patches. And expensive stages
*measure* rather than *decide*: they record every artifact with its
properties, and quality thresholds are applied afterwards as a saved
selection, so changing your mind costs seconds instead of hours.

## A study in five commands

```console
$ rocqipath study init colorectal_cd8 --source /mnt/archive/crc_2024
$ rocqipath study index colorectal_cd8      # find slides, decode identity
$ rocqipath study survey colorectal_cd8     # measure magnification, MPP, pyramid
$ rocqipath study verify colorectal_cd8     # fail in seconds, not three hours in
$ rocqipath study run colorectal_cd8        # alignment -> patches -> counts
```

The same flow from Python:

```python
from rocqipath import Study

study = Study.open("colorectal_cd8")
study.survey()
print(study.verify().format())

study.plan()                                  # writes recipe.json
study.run(["alignment", "patches", "counts"])

study.select("strict", tissue_fraction=0.60)  # QC as a saved view
print(study.results(selection="strict").format())
```

Everything RocqiPath writes lives under one root:

```
$ROCQIPATH_HOME/colorectal_cd8/
├── study.toml       you write this — the only hand-authored file
├── index.jsonl      generated: one line per physical slide
├── survey/          generated: what the slides actually are
├── recipe.json      generated: the resolved, hashed plan
├── alignment/  tissue/  patches/  stain/  counts/
├── selections/      named QC views over stage manifests
└── qc/  logs/
```

Slides are **referenced, never ingested**. Whole-slide images are large and
usually live on read-only storage, so a study points at them where they
already are.

Prefer explicit paths? Every original pipeline function still works exactly as
before — see [the pipeline API reference](docs/reference/python-api.md).

## Install

RocqiPath needs 64-bit Python 3.10 or 3.11. Python 3.11 is recommended: the
TIAToolbox/Numba stack does not support 3.12 or newer.

```console
$ git clone https://github.com/DarshilGajjar/RocqiPath.git
$ cd RocqiPath
$ python -m pip install -e .          # CLI, study workspace, shared utilities
```

Then add only the capabilities your workflow needs:

| Extra | Install | Gives you |
| --- | --- | --- |
| `extraction` | `pip install -e ".[extraction]"` | WSI and TMA tissue extraction |
| `orb` | `pip install -e ".[orb]"` | Contour/ORB registration, streamed aligned-WSI export |
| `valis` | `pip install -e ".[valis]"` | Rigid and non-rigid VALIS registration |
| `stain` | `pip install -e ".[stain]"` | Reinhard, Macenko, Vahadane normalisation |
| `cellcount` | `pip install -e ".[cellcount]"` | DAB-positive cell counting |
| `viz` | `pip install -e ".[viz]"` | Grid maps, paired QC figures, comparisons |

Extras combine: `pip install -e ".[extraction,cellcount,viz]"`.

Registration and pyramidal TIFF work also need the **native libvips** runtime,
and slide reading needs **OpenSlide**. `pip` does not install these on every
platform — see [native dependencies](docs/start/native-dependencies.md) for
per-OS instructions.

Something not working? Run `rocqipath doctor`. It prints your Python, platform,
native runtimes, installed extras, and workspace root in one block.

## Documentation

| | |
| --- | --- |
| **[Get started](docs/start/)** | Install, native runtimes, and a first study end to end |
| **[Guides](docs/guides/)** | Task-oriented recipes: align a pair, extract cores, count cells |
| **[Reference](docs/reference/)** | File formats, CLI, Python API, error messages |
| **[Concepts](docs/concepts/)** | Why physical magnification; survey to recipe to run; QC philosophy |
| **[FAQ](docs/faq.md)** | Short answers to recurring questions |

New here? Start with [your first study](docs/start/first-study.md).
Upgrading from a script-based workflow? See
[migrating to studies](docs/start/migrating-to-studies.md) — nothing you
already have breaks.

## Contributing and support

- [CONTRIBUTING.md](CONTRIBUTING.md) — before adding a module or public API
- [SUPPORT.md](SUPPORT.md) — supported Python, dependency, and maintenance policy
- [SECURITY.md](SECURITY.md) — vulnerability reports, **and the patient-data rules for issues**
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

**Never attach patient slides, filenames, or identifiers to a public issue.**
See [SECURITY.md](SECURITY.md) for how to report a problem safely.

## Citing RocqiPath

Cite RocqiPath itself, including the release version and this repository URL,
plus the underlying components that were materially used in the analysis you
report. You do not need to cite every utility dependency of every project.

[CITATION.md](CITATION.md) lists the full references for VALIS, TIAToolbox,
NumPy, and libvips, and [CITATION.cff](CITATION.cff) drives GitHub's
"Cite this repository" button.

## Status and licence

**Research software under active development.** The public API is not yet
stable; breaking changes are recorded in [CHANGELOG.md](CHANGELOG.md) and
announced in release notes. Pin a release for anything you intend to reproduce.

**RocqiPath is proprietary software — copyright © 2026 Darshil Gajjar, all
rights reserved.** The source is published for transparency, review, and
citation. Use, copying, modification, and redistribution require prior written
permission from the copyright holder. See [LICENSE](LICENSE) for the full
terms, and open an issue or contact the maintainer to discuss access.
