"""Report the environment RocqiPath is actually running in.

Most RocqiPath support questions reduce to one of a small number of
environment facts: which Python, whether the native libvips and OpenSlide
runtimes are on the path, which optional extras are installed, and where
``ROCQIPATH_HOME`` points.

``rocqipath doctor`` prints all of it in one block.  The bug report template
asks for that block, which turns "it doesn't work on my machine" into a
diagnosable report.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version as _distribution_version
from typing import Dict, List, Optional

from rocqipath.study.paths import HOME_ENV_VAR, resolve_home

__all__ = ["Diagnostics", "collect_diagnostics", "format_diagnostics"]

#: Python packages checked, mapped to the extra that provides them.
_OPTIONAL_PACKAGES = {
    "numpy": "extraction",
    "cv2": "extraction",
    "PIL": "extraction",
    "openslide": "extraction",
    "pyvips": "orb",
    "valis": "valis",
    "tiatoolbox": "stain",
    "skimage": "cellcount",
    "matplotlib": "viz",
    "tqdm": "extraction",
}

#: Native runtimes checked on ``PATH``.
_NATIVE_TOOLS = {
    "vips": "libvips (pyramidal TIFF I/O, aligned-WSI export)",
    "openslide-show-properties": "OpenSlide (whole-slide reading)",
}


@dataclass
class Diagnostics:
    """A snapshot of the running environment.

    Attributes
    ----------
    rocqipath_version : str
        Installed package version.
    python_version, python_executable, platform_name : str
        Interpreter and operating-system details.
    home : str
        Resolved workspace root.
    home_source : str
        Whether the root came from the environment or the default.
    packages : dict
        Import name mapped to a version string or a "not installed" note.
    native : dict
        Native tool name mapped to its resolved path or a "not found" note.
    problems : list of str
        Things likely to break a run.
    """

    rocqipath_version: str = ""
    python_version: str = ""
    python_executable: str = ""
    platform_name: str = ""
    home: str = ""
    home_source: str = ""
    packages: Dict[str, str] = field(default_factory=dict)
    native: Dict[str, str] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        """Serialise these diagnostics."""
        return {
            "rocqipath_version": self.rocqipath_version,
            "python_version": self.python_version,
            "python_executable": self.python_executable,
            "platform": self.platform_name,
            "home": self.home,
            "home_source": self.home_source,
            "packages": self.packages,
            "native": self.native,
            "problems": self.problems,
        }


def _package_version(module_name: str) -> Optional[str]:
    """Return an importable module's version string, or ``None`` if absent."""
    try:
        module = import_module(module_name)
    except (ImportError, OSError):
        return None
    for attribute in ("__version__", "VERSION", "version"):
        value = getattr(module, attribute, None)
        if isinstance(value, str) and value:
            return value
    return "installed"


def collect_diagnostics() -> Diagnostics:
    """Inspect the environment and return the findings.

    Returns
    -------
    Diagnostics
        A snapshot suitable for pasting into a bug report.
    """
    try:
        installed = _distribution_version("rocqipath")
    except PackageNotFoundError:
        installed = "0+unknown (not installed as a distribution)"

    from_env = os.environ.get(HOME_ENV_VAR, "").strip()
    report = Diagnostics(
        rocqipath_version=installed,
        python_version=sys.version.split()[0],
        python_executable=sys.executable,
        platform_name=f"{platform.system()} {platform.release()} ({platform.machine()})",
        home=str(resolve_home()),
        home_source=HOME_ENV_VAR if from_env else "default (~/rocqipath)",
    )

    for module_name, extra in sorted(_OPTIONAL_PACKAGES.items()):
        found = _package_version(module_name)
        report.packages[module_name] = (
            found if found else f"not installed — provided by the '{extra}' extra"
        )

    for tool, purpose in sorted(_NATIVE_TOOLS.items()):
        located = shutil.which(tool)
        report.native[tool] = located or f"NOT FOUND on PATH — needed for {purpose}"

    if sys.version_info >= (3, 12):
        report.problems.append(
            "Python 3.12 or newer is not supported: the TIAToolbox/Numba stack "
            "requires 3.10 or 3.11."
        )
    if not shutil.which("vips"):
        report.problems.append(
            "libvips was not found on PATH. Pyramidal TIFF writing and aligned-WSI "
            "export will fail. See docs/start/native-dependencies.md."
        )
    if _package_version("openslide") is None:
        report.problems.append(
            "openslide-python is not importable. Whole-slide reading will fall back "
            'to PIL. Install with: python -m pip install -e ".[extraction]"'
        )
    if not from_env:
        report.problems.append(
            f"{HOME_ENV_VAR} is not set; studies will be written to ~/rocqipath. "
            "See docs/start/install.md to set it permanently."
        )
    return report


def format_diagnostics(report: Optional[Diagnostics] = None) -> str:
    """Render diagnostics as the block a bug report should contain.

    Parameters
    ----------
    report : Diagnostics, optional
        Pre-collected diagnostics.  Collected fresh when omitted.

    Returns
    -------
    str
        A printable multi-line report.
    """
    data = report or collect_diagnostics()
    lines = [
        "RocqiPath environment report",
        "=" * 60,
        f"rocqipath        {data.rocqipath_version}",
        f"python           {data.python_version}",
        f"executable       {data.python_executable}",
        f"platform         {data.platform_name}",
        f"{HOME_ENV_VAR:<16} {data.home}  [{data.home_source}]",
        "",
        "Native runtimes",
        "-" * 60,
    ]
    for tool, status in data.native.items():
        lines.append(f"{tool:<30} {status}")
    lines += ["", "Python packages", "-" * 60]
    for module_name, status in data.packages.items():
        lines.append(f"{module_name:<30} {status}")
    if data.problems:
        lines += ["", "Problems detected", "-" * 60]
        lines.extend(f"- {problem}" for problem in data.problems)
    else:
        lines += ["", "No problems detected."]
    return "\n".join(lines)
