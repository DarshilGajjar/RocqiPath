"""The worked example in docs/contributing/adding-a-workflow.md must run."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rocqipath.registry import WORKFLOWS

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "contributing" / "adding-a-workflow.md"


@pytest.fixture
def unregister():
    yield
    WORKFLOWS.pop("measure_tissue", None)


def test_adding_a_workflow_guide_runs(tmp_path, unregister):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    blocks = re.findall(r"```python\n(.*?)```", GUIDE.read_text(encoding="utf-8"), flags=re.DOTALL)
    assert len(blocks) == 3
    namespace = {"tmp": tmp_path}
    for block in blocks:
        exec(compile(block, str(GUIDE), "exec"), namespace)
    assert "measure_tissue" in WORKFLOWS
