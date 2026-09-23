"""Which importable modules each ``pip install rocqipath[<extra>]`` provides.

The CLI's ``rocqipath list`` and Studio use this table to report whether a
workflow can run. ``tests/test_extras.py`` checks it against
``pyproject.toml`` so the two cannot drift.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Dict, List, Tuple

#: Extra name mapped to the top-level modules it must make importable.
EXTRA_MODULES: Dict[str, Tuple[str, ...]] = {
    "extraction": ("numpy", "cv2", "pyvips", "openslide", "PIL", "tqdm"),
    "semantic": ("tiatoolbox", "zarr"),
    "orb": ("numpy", "cv2", "pyvips", "openslide", "PIL", "tqdm"),
    "valis": ("numpy", "cv2", "pyvips", "openslide", "PIL", "tqdm", "valis", "matplotlib"),
    "stain": ("numpy", "cv2", "tiatoolbox"),
    "cellcount": ("numpy", "cv2", "openslide", "skimage", "tqdm", "PIL", "matplotlib", "openpyxl"),
    "viz": ("numpy", "cv2", "matplotlib", "PIL"),
    "studio": ("fastapi", "uvicorn"),
}

#: Modules wrapping native libraries: finding the package is not enough,
#: the shared library must load too.
_NATIVE = {"pyvips", "openslide"}


def module_available(name: str) -> bool:
    """Return whether ``name`` imports, loading native libraries when relevant."""
    try:
        if importlib.util.find_spec(name) is None:
            return False
        if name in _NATIVE:
            importlib.import_module(name)
        return True
    except Exception:
        return False


def missing_modules(extra: str) -> List[str]:
    """Modules of ``extra`` that cannot be imported in this environment."""
    return [name for name in EXTRA_MODULES[extra] if not module_available(name)]


__all__ = ["EXTRA_MODULES", "missing_modules", "module_available"]
