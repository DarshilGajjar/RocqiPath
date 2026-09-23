"""Whole-slide registration of a moving slide onto a reference slide.

Most users call :func:`rocqipath.align`. :class:`WSIRegistrar` registers and
exports one slide pair directly for finer control.
"""

from rocqipath._internal.lazy import lazy_exports

__getattr__, __dir__, __all__ = lazy_exports(
    __name__,
    {
        "AlignConfig": ".config",
        "AlignedCaseResult": ".models",
        "OrbOptions": ".config",
        "ValisOptions": ".config",
        "WSIRegistrar": ".registrar",
    },
)
