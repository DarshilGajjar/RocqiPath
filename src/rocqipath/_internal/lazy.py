"""Lazy attribute loading for package ``__init__`` modules.

Packages list their public names and the submodule defining each. Nothing is
imported until a name is first used, so ``import rocqipath.alignment`` (or
its lightweight ``config`` module) never loads OpenCV, libvips or VALIS.
"""

from __future__ import annotations

import importlib
from typing import Callable, Dict, List, Tuple


def lazy_exports(
    package: str, exports: Dict[str, str]
) -> Tuple[Callable[[str], object], Callable[[], List[str]], List[str]]:
    """Build ``__getattr__``, ``__dir__`` and ``__all__`` for a package.

    Parameters
    ----------
    package : str
        The package's ``__name__``.
    exports : dict
        Public name mapped to the module that defines it, either absolute
        (``"rocqipath.io.slide"``) or relative to ``package`` (``".slide"``).

    Returns
    -------
    tuple
        ``(__getattr__, __dir__, __all__)`` to assign in the package.
    """

    def __getattr__(name: str) -> object:
        try:
            module_name = exports[name]
        except KeyError:
            raise AttributeError(f"module {package!r} has no attribute {name!r}") from None
        value = getattr(importlib.import_module(module_name, package), name)
        setattr(importlib.import_module(package), name, value)
        return value

    def __dir__() -> List[str]:
        return sorted(exports)

    return __getattr__, __dir__, sorted(exports)


__all__ = ["lazy_exports"]
