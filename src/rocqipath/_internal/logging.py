"""Shared standard-library logging configuration."""

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

_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=_FORMAT, datefmt="%H:%M:%S")

# Keep noisy libvips/pyvips diagnostic messages out of the console.
# Genuine pyvips errors are still allowed through.
logging.getLogger("pyvips").setLevel(logging.ERROR)

logger = logging.getLogger("rocqipath")
_FILE_HANDLERS: dict[Path, logging.FileHandler] = {}


def get_logger(name: str) -> logging.Logger:
    """Return a child of the shared RocqiPath logger."""
    return logging.getLogger(f"rocqipath.{name}")


def set_log_level(level: str) -> None:
    """Set the RocqiPath logger and its handlers to ``level``."""
    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        raise ValueError(f"Unknown log level: {level!r}")
    logger.setLevel(numeric_level)
    for handler in logger.handlers:
        handler.setLevel(numeric_level)


def add_log_file(path: str | Path, *, level: str = "DEBUG") -> None:
    """Add or replace a UTF-8 file handler for ``path``."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    previous = _FILE_HANDLERS.pop(resolved, None)
    if previous is not None:
        logger.removeHandler(previous)
        previous.close()

    handler = logging.FileHandler(resolved, encoding="utf-8")
    handler.setLevel(level.upper())
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    _FILE_HANDLERS[resolved] = handler


def configure_logging(
    save_dir: str | Path | None = None,
    *,
    file_level: str = "DEBUG",
    log_filename: str = "rocqipath.log",
) -> None:
    """Configure console logging and optionally add a pipeline log file."""
    logging.basicConfig(level=logging.INFO, format=_FORMAT, datefmt="%H:%M:%S")
    if save_dir is not None:
        add_log_file(Path(save_dir) / log_filename, level=file_level)