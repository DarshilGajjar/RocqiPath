"""Protect lightweight imports from accidental heavy optional dependencies."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BLOCKED_MODULES = {
    "PIL",
    "cv2",
    "matplotlib",
    "numpy",
    "openslide",
    "pyvips",
    "skimage",
    "tiatoolbox",
    "valis",
}


def test_lightweight_modules_import_with_heavy_dependencies_blocked() -> None:
    """Import the currently available lightweight surface in a fresh process."""
    source_root = Path(__file__).resolve().parents[1] / "src"
    script = f"""
import importlib.abc
import sys

blocked = {sorted(BLOCKED_MODULES)!r}

class BlockHeavyModules(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in blocked:
            raise ImportError(f"blocked optional dependency: {{fullname}}")
        return None

sys.meta_path.insert(0, BlockHeavyModules())
import rocqipath
import rocqipath.core
import rocqipath.utils
import rocqipath.utils.discovery
import rocqipath.utils.geometry
import rocqipath.utils.imageio
import rocqipath.utils.manifest
import rocqipath.utils.naming
import rocqipath.utils.reporting
import rocqipath.utils.validation
import rocqipath.utils.vips
loaded = {{name.split(".", 1)[0] for name in sys.modules}}
unexpected = sorted(set(blocked) & loaded)
if unexpected:
    raise AssertionError(f"heavy modules imported: {{unexpected}}")
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
