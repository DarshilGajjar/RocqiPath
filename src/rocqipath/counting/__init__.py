"""DAB-positive cell counting.

Most users call :func:`rocqipath.count_cells`. :class:`PositiveCellCounter`
counts single patches or slides directly.
"""

from rocqipath._internal.lazy import lazy_exports

__getattr__, __dir__, __all__ = lazy_exports(
    __name__,
    {
        "CountCellsConfig": ".config",
        "PositiveCellCounter": ".counter",
    },
)
