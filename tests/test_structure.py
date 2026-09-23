"""Layout rules: every module name is unique and every helper has one home."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "rocqipath"
SINGLE_DEFINITION = ("tissue_fraction", "list_wsi_files")


def _modules():
    return [p for p in PACKAGE.rglob("*.py") if p.name not in {"__init__.py", "__main__.py"}]


@pytest.mark.xfail(reason="Phase 1 of the 2.0 restructure removes duplicate module names", strict=True)
def test_module_basenames_are_unique():
    counts = Counter(p.name for p in _modules())
    assert [name for name, n in counts.items() if n > 1] == []


@pytest.mark.xfail(reason="Phase 1 of the 2.0 restructure deduplicates helpers", strict=True)
@pytest.mark.parametrize("name", SINGLE_DEFINITION)
def test_helper_defined_once(name):
    homes = [
        p.relative_to(PACKAGE).as_posix()
        for p in _modules()
        for node in ast.parse(p.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(homes) == 1, homes
