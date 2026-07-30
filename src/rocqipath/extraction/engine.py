"""Shared setup and magnification primitives for extraction pipelines."""

from __future__ import annotations
import logging
from typing import Any, Optional, Tuple
from rocqipath.core.logging import (
    add_log_file,
    configure_logging as _configure_shared_logging,
)
from rocqipath.core.magnification import objective_magnification_from_properties
from rocqipath.utils.vips import vips_properties as _vips_properties

for _n in ("pyvips", "VIPS", "PIL", "PIL.Image", "PIL.TiffImagePlugin", "matplotlib", "openslide"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)
SUPPORTED_EXTENSIONS: frozenset = frozenset({".tif", ".tiff", ".svs"})


def configure_logging(
    save_dir: Optional[str] = None,
    *,
    file_level: str = "DEBUG",
    log_filename: str = "extraction.log",
) -> None:
    """Attach a persistent loguru file sink inside ``save_dir``.

    The sink is added alongside the module-level stderr sink configured
    at import time.

    Parameters
    ----------
    save_dir : str, optional
        Directory in which to create the log file. Created if it doesn't
        already exist. If ``None`` (the default), this function is a
        no-op — no file sink is added, and logging continues to go only
        to stderr via the sink configured at module import time.
    file_level : str, optional
        Minimum log level written to the file sink (e.g. ``"DEBUG"``,
        ``"INFO"``). Case-insensitive; uppercased internally to match
        loguru's expected level names. Defaults to ``"DEBUG"`` so the
        file captures more detail than typically shown on the console.
    log_filename : str, optional
        Name of the log file created inside ``save_dir``. Defaults to
        ``"extraction.log"``; pipeline modules typically override this
        with a more specific name (e.g. ``"core_extraction.log"``).

    Notes
    -----
    Each call adds a *new* sink via :func:`loguru.logger.add` — calling
    this function multiple times (e.g. once per pipeline run within the
    same process) will accumulate multiple file sinks rather than
    replacing the previous one. The added sink has no rotation
    (``rotation=None``) and writes UTF-8 text with a
    ``"{time} | {level} | {message}"`` format (without the colour tags
    used by the console sink, since log files are typically viewed in a
    plain text editor).
    """
    _configure_shared_logging(
        save_dir,
        file_level=file_level,
        log_filename=log_filename,
        add_file_sink=add_log_file,
    )


def _resolve_vips_magnification(img: Any, fallback: Optional[float]) -> Tuple[float, str]:
    """Resolve a pyvips image's objective magnification and metadata source."""
    return objective_magnification_from_properties(_vips_properties(img), fallback=fallback)
