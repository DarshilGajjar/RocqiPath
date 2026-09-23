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
import rocqipath.errors
import rocqipath.io
import rocqipath.tissue
import rocqipath._internal.console
import rocqipath._internal.logging
import rocqipath.io.discovery
import rocqipath._internal.geometry
import rocqipath.io.images
import rocqipath.io.manifest
import rocqipath.io.naming
import rocqipath._internal.config_panel
import rocqipath._internal.validation
import rocqipath.io.vips
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
