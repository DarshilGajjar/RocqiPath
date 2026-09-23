"""The extras table used by the CLI and Studio matches pyproject.toml."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import rocqipath as rp
from rocqipath.extras import EXTRA_MODULES

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PYPROJECT = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
EXTRAS = PYPROJECT["project"]["optional-dependencies"]
IMPORT_NAMES = {
    "opencv-python-headless": "cv2",
    "pillow": "PIL",
    "openslide-python": "openslide",
    "scikit-image": "skimage",
    "valis-wsi": "valis",
}


def _module(requirement: str) -> str:
    name = re.split(r"[<>=\[; ]", requirement, maxsplit=1)[0].lower()
    return IMPORT_NAMES.get(name, name.replace("-", "_"))


def test_every_runtime_extra_is_described() -> None:
    assert set(EXTRA_MODULES) == set(EXTRAS) - {"test", "docs"}


def test_described_modules_are_what_each_extra_installs() -> None:
    for extra, modules in EXTRA_MODULES.items():
        assert set(modules) == {_module(r) for r in EXTRAS[extra]}, extra


def test_every_workflow_names_a_real_extra() -> None:
    for workflow in rp.list_workflows():
        assert workflow.extra in EXTRA_MODULES, workflow.name
