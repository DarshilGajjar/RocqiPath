"""Shared logging configuration for RocqiPath.

RocqiPath is silent by default when used as a Python library.

The package never configures Python's root logger. This prevents logging
configuration from leaking into third-party libraries such as pyvips,
VALIS, OpenSlide, PyTorch, or user applications.

Console logging can be enabled explicitly with ``configure_logging()``.
"""

from __future__ import annotations

import logging
from pathlib import Path


__all__ = [
    "add_log_file",
    "configure_logging",
    "get_logger",
    "logger",
    "set_log_level",
]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"


# ---------------------------------------------------------------------------
# Main RocqiPath logger
# ---------------------------------------------------------------------------

logger = logging.getLogger("rocqipath")

# Keep the logger permissive internally. Individual handlers determine
# which records are actually emitted.
logger.setLevel(logging.DEBUG)

# CRITICAL:
# Do not allow RocqiPath messages to propagate to the application's
# root logger. RocqiPath manages only its own handlers.
logger.propagate = False


# ---------------------------------------------------------------------------
# Silent-by-default library behavior
# ---------------------------------------------------------------------------

if not any(
    isinstance(handler, logging.NullHandler)
    for handler in logger.handlers
):
    logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Suppress noisy third-party dependency logging
# ---------------------------------------------------------------------------

# pyvips redirects native libvips/GLib messages into Python logging.
# INFO and WARNING messages can be extremely verbose during WSI processing.
#
# Keep ERROR/CRITICAL available while suppressing normal libvips diagnostic
# chatter.
logging.getLogger("pyvips").setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_FILE_HANDLERS: dict[Path, logging.FileHandler] = {}

_CONSOLE_HANDLER: logging.StreamHandler | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _numeric_level(level: str) -> int:
    """Convert a logging level name to its numeric representation."""

    numeric_level = logging.getLevelName(level.upper())

    if not isinstance(numeric_level, int):
        raise ValueError(
            f"Unknown log level: {level!r}"
        )

    return numeric_level


def get_logger(name: str) -> logging.Logger:
    """Return a child logger of the shared RocqiPath logger.

    Parameters
    ----------
    name : str
        Child logger name.

    Returns
    -------
    logging.Logger
        Logger named ``rocqipath.<name>``.

    Notes
    -----
    Child loggers inherit RocqiPath's handler configuration and do not
    propagate beyond the ``rocqipath`` logger.
    """

    return logging.getLogger(
        f"rocqipath.{name}"
    )


# ---------------------------------------------------------------------------
# Logging level
# ---------------------------------------------------------------------------

def set_log_level(level: str) -> None:
    """Set the active RocqiPath logging level.

    This changes RocqiPath handlers only. It does not modify the Python
    root logger or third-party package loggers.

    Examples
    --------
    Show only errors:

    >>> set_log_level("ERROR")

    Show debugging information:

    >>> set_log_level("DEBUG")
    """

    numeric_level = _numeric_level(level)

    logger.setLevel(numeric_level)

    for handler in logger.handlers:
        if isinstance(handler, logging.NullHandler):
            continue

        handler.setLevel(numeric_level)


# ---------------------------------------------------------------------------
# File logging
# ---------------------------------------------------------------------------

def add_log_file(
    path: str | Path,
    *,
    level: str = "DEBUG",
) -> None:
    """Add or replace a UTF-8 RocqiPath file logger.

    File logging is independent of console logging. Therefore RocqiPath can
    remain completely silent in the terminal while still preserving a
    detailed debug log on disk.
    """

    resolved = (
        Path(path)
        .expanduser()
        .resolve()
    )

    resolved.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    previous = _FILE_HANDLERS.pop(
        resolved,
        None,
    )

    if previous is not None:
        logger.removeHandler(previous)
        previous.close()

    handler = logging.FileHandler(
        resolved,
        encoding="utf-8",
    )

    handler.setLevel(
        _numeric_level(level)
    )

    handler.setFormatter(
        logging.Formatter(
            _FORMAT,
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    logger.addHandler(handler)

    _FILE_HANDLERS[resolved] = handler


# ---------------------------------------------------------------------------
# Explicit logging configuration
# ---------------------------------------------------------------------------

def configure_logging(
    save_dir: str | Path | None = None,
    *,
    console: bool = False,
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    log_filename: str = "rocqipath.log",
) -> None:
    """Configure optional RocqiPath console and file logging.

    RocqiPath remains silent on the console unless ``console=True`` is
    explicitly requested.

    Unlike ``logging.basicConfig()``, this function configures only the
    ``rocqipath`` logger and therefore cannot accidentally enable logging
    from pyvips, VALIS, OpenSlide, or other dependencies.

    Parameters
    ----------
    save_dir : str or Path, optional
        Directory in which to save the RocqiPath log file.

    console : bool, default=False
        Enable RocqiPath console logging.

    console_level : str, default="INFO"
        Minimum console logging level.

    file_level : str, default="DEBUG"
        Minimum file logging level.

    log_filename : str, default="rocqipath.log"
        Log filename created inside ``save_dir``.

    Examples
    --------
    Keep console completely silent:

    >>> configure_logging()

    Enable RocqiPath console messages:

    >>> configure_logging(
    ...     console=True,
    ...     console_level="INFO",
    ... )

    Silent console with detailed file logging:

    >>> configure_logging(
    ...     save_dir="./output",
    ...     console=False,
    ...     file_level="DEBUG",
    ... )

    Show only warnings and errors:

    >>> configure_logging(
    ...     console=True,
    ...     console_level="WARNING",
    ... )
    """

    global _CONSOLE_HANDLER

    # ------------------------------------------------------------------
    # Console
    # ------------------------------------------------------------------

    if console:
        numeric_console_level = _numeric_level(
            console_level
        )

        if _CONSOLE_HANDLER is None:
            _CONSOLE_HANDLER = logging.StreamHandler()

            _CONSOLE_HANDLER.setFormatter(
                logging.Formatter(
                    _FORMAT,
                    datefmt="%H:%M:%S",
                )
            )

            logger.addHandler(
                _CONSOLE_HANDLER
            )

        _CONSOLE_HANDLER.setLevel(
            numeric_console_level
        )

    else:
        # Explicitly remove an existing console handler.
        if _CONSOLE_HANDLER is not None:
            logger.removeHandler(
                _CONSOLE_HANDLER
            )

            _CONSOLE_HANDLER.close()

            _CONSOLE_HANDLER = None

    # ------------------------------------------------------------------
    # File
    # ------------------------------------------------------------------

    if save_dir is not None:
        add_log_file(
            Path(save_dir) / log_filename,
            level=file_level,
        )

    # ------------------------------------------------------------------
    # Keep noisy dependencies quiet
    # ------------------------------------------------------------------

    logging.getLogger(
        "pyvips"
    ).setLevel(logging.ERROR)