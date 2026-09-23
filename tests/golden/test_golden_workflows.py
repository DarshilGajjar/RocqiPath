"""Golden snapshots proving the restructure keeps every workflow's behavior.

Each workflow runs on deterministic synthetic data. The snapshot records the
output file tree, the content of every JSON manifest, pixel statistics for
data images, and the workflow's return value. Regenerate snapshots with
``pytest tests/golden --update-golden`` only when a behavior change is
intended and reviewed.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import pytest

from tests.golden._calls import CALLS, REQUIRES

EXPECTED = Path(__file__).parent / "expected"
VOLATILE_KEYS = {"generated_at", "created", "timestamp", "elapsed_s", "duration_s", "rocqipath_version"}
IMAGE_SUFFIXES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
MEAN_TOLERANCE = 1.0


def _normalize(value: Any, root: str) -> Any:
    """Convert to JSON-safe, root-independent, rounding-stable data."""
    if isinstance(value, dict):
        return {
            str(k): _normalize(v, root) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            if str(k) not in VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(v, root) for v in value]
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        return value.replace(root, "<ROOT>")
    if hasattr(value, "item") and not isinstance(value, (bool, int, float)):
        value = value.item()
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 3)
    return value


def _image_entry(path: Path) -> dict:
    from PIL import Image

    with Image.open(path) as image:
        if str(image.info.get("Software", "")).lower().startswith("matplotlib"):
            return {"figure": True}
        entry: dict = {"size": list(image.size)}
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            return entry
        import numpy as np

        rgb = np.asarray(image.convert("RGB"), dtype=np.float64)
        entry["mean"] = [round(float(c), 1) for c in rgb.reshape(-1, 3).mean(axis=0)]
        return entry


def _file_entry(path: Path, root: str) -> Any:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _normalize(json.loads(path.read_text(encoding="utf-8")), root)
    if suffix in IMAGE_SUFFIXES:
        return _image_entry(path)
    if suffix == ".npz":
        import numpy as np

        with np.load(path, allow_pickle=False) as data:
            return {key: list(data[key].shape) for key in sorted(data.files)}
    return {}


def snapshot(output_dir: Path, returned: dict, root: Path) -> dict:
    """Describe one workflow run in a stable, reviewable form."""
    roots = sorted({str(root), str(root.resolve())}, key=len, reverse=True)

    def norm(value):
        for r in roots:
            value = _normalize(value, r)
        return value

    files = {}
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
        entry = _file_entry(path, str(root))
        files[path.relative_to(output_dir).as_posix()] = norm(entry)
    return {"returned": norm(returned), "files": files}


def _differences(actual: Any, expected: Any, path: str = "") -> list:
    """List mismatches; image means may differ by 1.0 across native library builds."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        if sorted(actual) != sorted(expected):
            return [f"{path}: keys {sorted(actual)} != {sorted(expected)}"]
        out = []
        for key in expected:
            sub = f"{path}/{key}"
            if key == "mean" and isinstance(expected[key], list):
                if len(actual[key]) != len(expected[key]) or any(
                    abs(a - e) > MEAN_TOLERANCE for a, e in zip(actual[key], expected[key])
                ):
                    out.append(f"{sub}: {actual[key]} != {expected[key]}")
            else:
                out.extend(_differences(actual[key], expected[key], sub))
        return out
    if isinstance(expected, list) and isinstance(actual, list) and len(actual) == len(expected):
        return [d for i, (a, e) in enumerate(zip(actual, expected)) for d in _differences(a, e, f"{path}[{i}]")]
    return [] if actual == expected else [f"{path}: {actual!r} != {expected!r}"]


def _missing(modules) -> list:
    return [m for m in modules if importlib.util.find_spec(m) is None]


@pytest.mark.parametrize("name", sorted(CALLS))
def test_golden(name, tmp_path, request, monkeypatch):
    missing = _missing(REQUIRES[name])
    if missing:
        pytest.skip(f"requires {', '.join(missing)}")
    import matplotlib

    matplotlib.use("Agg")
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "work"
    root.mkdir()
    output_dir, returned = CALLS[name](root)
    actual = snapshot(output_dir, returned, root)
    expected_path = EXPECTED / f"{name}.json"
    if request.config.getoption("--update-golden"):
        expected_path.parent.mkdir(exist_ok=True)
        expected_path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    assert expected_path.exists(), f"no golden snapshot for {name}; run with --update-golden"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert sorted(actual["files"]) == sorted(expected["files"]), "output file tree changed"
    assert _differences(actual["files"], expected["files"]) == [], "output file content changed"
    assert _differences(actual["returned"], expected["returned"]) == [], "return value changed"
