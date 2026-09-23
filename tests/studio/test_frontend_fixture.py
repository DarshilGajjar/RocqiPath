"""The frontend tests render the real workflow schemas; keep their snapshot current.

Regenerate with::

    python -m rocqipath.studio.catalog > studio-web/src/test/workflows.json
"""

from __future__ import annotations

import json
from pathlib import Path

from rocqipath.studio.catalog import catalog

FIXTURE = Path(__file__).resolve().parents[2] / "studio-web" / "src" / "test" / "workflows.json"


def _normalized(entries):
    for entry in entries:
        entry["available"] = True
        entry["missing"] = []
    return json.loads(json.dumps(entries, default=str))


def test_frontend_fixture_matches_the_workflow_catalog() -> None:
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == _normalized(catalog())
