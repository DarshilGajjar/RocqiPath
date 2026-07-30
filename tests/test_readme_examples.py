"""Execute the README's Python examples against the installed public API."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


README = Path(__file__).parents[1] / "README.md"
PYTHON_BLOCKS = re.findall(
    r"```python\n(.*?)```",
    README.read_text(encoding="utf-8"),
    flags=re.DOTALL,
)


@pytest.mark.parametrize(
    "source",
    PYTHON_BLOCKS,
    ids=[f"python-block-{index}" for index in range(1, len(PYTHON_BLOCKS) + 1)],
)
def test_readme_python_examples_reach_data_boundary(
    source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run each example until completion or its documented missing-data boundary."""
    monkeypatch.chdir(tmp_path)
    try:
        exec(compile(source, str(README), "exec"), {})
    except FileNotFoundError:
        pass
