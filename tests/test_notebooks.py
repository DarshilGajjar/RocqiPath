"""Notebooks compile and only use names that exist in the public API."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import rocqipath as rp

NOTEBOOKS = sorted((Path(__file__).resolve().parents[1] / "how_to_use").glob("*.ipynb"))


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_notebook_code_compiles_against_the_public_api(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    sources = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
    for index, source in enumerate(sources):
        compile(source, f"{path.name} cell {index}", "exec")
    used = set(re.findall(r"\brp\.([A-Za-z_]+)", "\n".join(sources)))
    assert used <= set(dir(rp)) | {"__version__"}, used - set(dir(rp))


def test_there_is_a_notebook_for_each_topic() -> None:
    assert len(NOTEBOOKS) == 9
