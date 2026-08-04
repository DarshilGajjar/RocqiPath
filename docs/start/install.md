# Installation

## Python version

RocqiPath requires **64-bit Python 3.10 or 3.11**. Python 3.11 is recommended.

Python 3.12 and newer are not supported: the TIAToolbox and Numba stack that
backs stain normalisation does not yet build against them. A 32-bit
interpreter cannot address a whole-slide pyramid and will fail at read time.

```console
$ python -c "import sys, struct; print(sys.version, struct.calcsize('P') * 8, 'bit')"
```

## Install the package

```console
$ git clone https://github.com/DarshilGajjar/RocqiPath.git
$ cd RocqiPath
$ python -m venv .venv
$ source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
$ python -m pip install -e .
```

The base install gives you the CLI, the study workspace, the magnification
model, logging, and shared utilities — with only `rich` and `loguru` as
dependencies. It deliberately pulls in no image backend, so it installs in
seconds and works anywhere.

## Add the extras you need

| Extra | Command | Gives you |
| --- | --- | --- |
| `extraction` | `pip install -e ".[extraction]"` | WSI and TMA tissue extraction |
| `orb` | `pip install -e ".[orb]"` | ORB registration, streamed aligned-WSI export |
| `valis` | `pip install -e ".[valis]"` | Rigid and non-rigid VALIS registration |
| `stain` | `pip install -e ".[stain]"` | Reinhard, Macenko, Vahadane normalisation |
| `cellcount` | `pip install -e ".[cellcount]"` | Chromogen-positive cell counting |
| `viz` | `pip install -e ".[viz]"` | Grid maps, paired QC figures, comparisons |

Extras combine:

```console
$ python -m pip install -e ".[extraction,cellcount,viz]"
```

Use `orb` if you want registration and aligned-WSI export without installing
the much heavier VALIS stack. Use `valis` when you need non-rigid alignment.

## Native runtimes

`pip` does not install the native **libvips** and **OpenSlide** libraries on
every platform, and RocqiPath cannot read most vendor slide formats without
them. Follow [native dependencies](native-dependencies.md) before your first
real run.

## Set the workspace root

RocqiPath writes every study beneath one directory, named by the
`ROCQIPATH_HOME` environment variable. It defaults to `~/rocqipath`, but
setting it explicitly is worth the thirty seconds: studies routinely reach
hundreds of gigabytes, and you will want them on a large, fast volume.

**Linux and macOS** — add to `~/.bashrc` or `~/.zshrc`:

```bash
export ROCQIPATH_HOME="/data/rocqipath"
```

**Windows PowerShell** — persist for your user account:

```powershell
[Environment]::SetEnvironmentVariable("ROCQIPATH_HOME", "D:\rocqipath", "User")
```

Reopen the terminal, then confirm:

```console
$ rocqipath doctor
```

## Verify the install

```console
$ rocqipath doctor
```

The report names your Python, platform, native runtimes, installed extras, and
resolved workspace root, and lists anything likely to break a run. Paste it
into a bug report if you open one.

## Development install

```console
$ python -m pip install -e ".[orb,cellcount,viz]"
$ python -m pip install "pytest>=7.4" "ruff>=0.4"
$ python -m pytest
$ python -m ruff check src tests
$ python -m ruff format --check src tests
```

Development tools are installed separately on purpose; they are not runtime
dependencies. CI runs unit tests and scanner-free synthetic integration tests
on Python 3.10 and 3.11. Tests against real scanner files stay local and must
use non-identifiable data.
