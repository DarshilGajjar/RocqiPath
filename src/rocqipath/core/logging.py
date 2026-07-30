"""Shared loguru configuration, exception reporting, and timing helpers."""

from __future__ import annotations

import functools
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger as _loguru_logger
from rich.traceback import install as _install_traceback

from .console import console

__all__ = [
    "logger",
    "get_logger",
    "set_log_level",
    "add_log_file",
    "configure_logging",
    "install_traceback",
    "log_exception",
    "Timer",
    "timed",
]

_loguru_logger.remove()


_CONSOLE_SINK_ID = _loguru_logger.add(
    sys.stderr,
    level="INFO",
    format=("<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}"),
    colorize=True,
)


logger = _loguru_logger


_FILE_SINKS: dict[str, int] = {}


def get_logger(name: str):
    """
    Return the shared library logger bound with a module tag.

    The returned object is the same loguru logger — ``name`` is stored as
    extra context so structured log sinks can filter by module if needed.

        from rocqipath.logger import get_logger
        _log = get_logger("core")
        _log.info("Registering {}", case_id)

    Parameters
    ----------
    name : str
        Sub-module tag, e.g. ``"core"``, ``"alignment"``, ``"extraction"``.
    """
    return logger.bind(module=name)


def set_log_level(level: str) -> None:
    """
    Change the log level for all rocqipath output at runtime.

        from rocqipath.logger import set_log_level
        set_log_level("DEBUG")    # show all messages
        set_log_level("WARNING")  # only warnings and above

    Parameters
    ----------
    level : str   ``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ``"ERROR"``
    """
    global _CONSOLE_SINK_ID
    logger.remove(_CONSOLE_SINK_ID)
    _CONSOLE_SINK_ID = logger.add(
        sys.stderr,
        level=level.upper(),
        format=("<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}"),
        colorize=True,
    )
    logger.debug("Log level → {}", level.upper())


def add_log_file(path: str, *, level: str = "DEBUG") -> None:
    """
    Write log output to a file in addition to stderr.

    Safe to call multiple times — each call adds a new file sink.

        from rocqipath.logger import add_log_file
        add_log_file("./output/run.log")
        add_log_file("./output/errors.log", level="WARNING")

    Parameters
    ----------
    path  : str   destination file path (parent directories are created)
    level : str   minimum level for this sink (default ``"DEBUG"``)
    """
    resolved = str(Path(path).resolve())
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    previous = _FILE_SINKS.pop(resolved, None)
    if previous is not None:
        logger.remove(previous)
    _FILE_SINKS[resolved] = logger.add(
        resolved,
        level=level.upper(),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        encoding="utf-8",
        rotation=None,
    )


def configure_logging(
    save_dir: str | Path | None = None,
    *,
    file_level: str = "DEBUG",
    log_filename: str = "extraction.log",
    reset: bool = False,
    logger_instance: Any | None = None,
    add_file_sink: Callable[..., None] | None = None,
    console_sink: Any = None,
    console_format: str | None = None,
    colorize: bool = True,
    rotation: str | None = None,
    retention: int | None = None,
    banner: str | None = None,
) -> None:
    """Configure either additive pipeline logging or a reset tool logger.

    The two modes intentionally preserve RocqiPath's historical logging
    contracts. Additive mode attaches only a file sink. Reset mode replaces
    every sink, adds a console sink, optionally adds a rotating file sink,
    and emits ``banner``.
    """
    active_logger = logger if logger_instance is None else logger_instance
    if reset:
        active_logger.remove()
        active_logger.add(
            sys.stdout if console_sink is None else console_sink,
            format=console_format,
            level="INFO",
            colorize=colorize,
        )
        if save_dir is not None:
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            log_path = str(Path(save_dir) / log_filename)
            active_logger.add(
                log_path,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
                level=file_level,
                rotation=rotation,
                retention=retention,
            )
        if banner is not None:
            active_logger.info(banner)
        return

    if save_dir is None:
        return
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    sink = add_log_file if add_file_sink is None else add_file_sink
    sink(
        str((Path(save_dir) / log_filename).resolve()),
        level=file_level,
    )


def install_traceback(show_locals: bool = False) -> None:
    """
    Replace Python's default exception hook with a Rich traceback.

        from rocqipath.logger import install_traceback
        install_traceback()
        install_traceback(True)   # also show local variables

    Parameters
    ----------
    show_locals : bool
        Print local variables for every stack frame when ``True``.
    """
    _install_traceback(console=console, show_locals=show_locals)


def log_exception(exc: BaseException, label: str = "") -> None:
    """
    Log an exception at ERROR level and print a Rich traceback.

        try:
            register_slides()
        except Exception as e:
            log_exception(e, "registration failed")

    Parameters
    ----------
    exc   : BaseException
    label : str   optional context string prepended to the message
    """
    prefix = f"{label}: " if label else ""
    logger.error("{}{}", prefix, exc)
    console.print_exception(show_locals=False)


class Timer:
    """
    Context manager **and** decorator that logs elapsed wall-clock time.

    Context manager
    ---------------
        from rocqipath.logger import Timer
        with Timer("VALIS registration"):
            registrar.register()
        # → DEBUG  ⏱  VALIS registration — 12.34 s

    Decorator
    ---------
        @Timer("warp_slide")
        def warp_slide(slide_obj, level=0):
            ...

    Parameters
    ----------
    label   : str
        Description logged with the elapsed time.
    logger_ : logging.Logger, optional
        Logger to write the timing to.  Defaults to the ``rocqipath``
        root logger.  Pass ``None`` to use ``print_info`` instead.
    level   : int
        Log level for the timing message (default ``logging.DEBUG``).
    """

    def __init__(
        self,
        label: str = "Task",
        logger_: Optional[logging.Logger] = None,
        level: int = logging.DEBUG,
    ) -> None:
        """Store the timing configuration; the clock starts on ``__enter__``.

        Parameters
        ----------
        label : str, optional
            Description logged alongside the elapsed time. Defaults to
            ``"Task"``. When used as a decorator (see :meth:`__call__`)
            and ``label`` is falsy, the wrapped function's ``__name__``
            is used instead.
        logger_ : logging.Logger, optional
            Logger to write the timing message to via
            :meth:`logging.Logger.log`. Defaults to the module-level
            ``rocqipath`` logger. Pass ``None`` explicitly to fall back to
            :func:`console.print` instead of the logging system.
        level : int, optional
            Log level (from the :mod:`logging` module) for the timing
            message. Defaults to ``logging.DEBUG`` so routine timings
            don't clutter INFO-level output.
        """
        self.label = label
        self._log = logger_ if logger_ is not None else logger
        self._level = level
        self._start: float = 0.0

    def __enter__(self) -> "Timer":
        """Record the start time and return ``self`` for the ``with`` block.

        Returns
        -------
        Timer
            This instance, enabling ``with Timer("label") as t:`` should
            callers want access to the timer object inside the block
            (though typically it is unused).
        """
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        """Compute the elapsed time since ``__enter__`` and log it.

        Parameters
        ----------
        *_ : Any
            The standard ``(exc_type, exc_value, traceback)`` triple
            passed by the context-manager protocol. Ignored — the elapsed
            time is logged unconditionally, whether or not the ``with``
            block raised, since timing information is useful either way.
        """
        self._emit(time.perf_counter() - self._start)

    def __call__(self, func: Callable) -> Callable:
        """Wrap ``func`` so every call logs its own elapsed execution time.

        Enables using a ``Timer`` instance as a decorator:
        ``@Timer("label")`` above a function definition.

        Parameters
        ----------
        func : Callable
            The function to wrap. Its signature is preserved via
            :func:`functools.wraps`.

        Returns
        -------
        Callable
            A wrapper function with the same signature as ``func`` that
            times each invocation and logs it under ``self.label`` (or
            ``func.__name__`` if ``self.label`` is falsy), then returns
            ``func``'s original return value unchanged.
        """
        lbl = self.label or func.__name__

        @functools.wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            """Call the wrapped function, timing and logging its execution.

            Parameters
            ----------
            *args, **kwargs
                Forwarded verbatim to the wrapped function.

            Returns
            -------
            Any
                Whatever the wrapped function returns, unmodified.
            """
            t0 = time.perf_counter()
            result = func(*args, **kwargs)
            self._emit(time.perf_counter() - t0, label=lbl)
            return result

        return _wrapper

    def _emit(self, elapsed: float, label: Optional[str] = None) -> None:
        """Format an elapsed duration as a human-readable string and log it.

        Parameters
        ----------
        elapsed : float
            Elapsed time in seconds (as returned by
            :func:`time.perf_counter` differences).
        label : str, optional
            Override for ``self.label`` used just for this call — used by
            the decorator path (:meth:`__call__`) where each wrapped
            function needs its own name instead of the ``Timer``
            instance's shared label. When omitted, ``self.label`` is used.

        Notes
        -----
        The duration is scaled for readability: minutes when
        ``elapsed >= 60``, seconds when ``elapsed >= 1``, otherwise
        milliseconds. The formatted message is sent to ``self._log`` (via
        :meth:`logging.Logger.log` at ``self._level``) if a logger was
        configured, otherwise printed directly via :func:`console.print`.
        """
        lbl = label or self.label
        if elapsed >= 60:
            human = f"{elapsed / 60:.1f} min"
        elif elapsed >= 1:
            human = f"{elapsed:.2f} s"
        else:
            human = f"{elapsed * 1000:.1f} ms"
        msg = f"[meta]\u23f1  {lbl}[/meta] \u2014 [bold white]{human}[/bold white]"
        if self._log:
            self._log.log(self._level, msg)
        else:
            console.print(msg)


def timed(label: str = "") -> Callable:
    """Log elapsed time for a decorated function.

    Shorthand for ``@Timer(label)``:

        from rocqipath.logger import timed

        @timed("patch extraction")
        def extract_patches(slide, level=2):
            ...

    Parameters
    ----------
    label : str   description; defaults to the function name when empty
    """

    def _decorator(func: Callable) -> Callable:
        """Apply a :class:`Timer` to ``func`` using the enclosing ``label``.

        Parameters
        ----------
        func : Callable
            The function being decorated by ``@timed(label)``.

        Returns
        -------
        Callable
            The timed wrapper produced by ``Timer(...).__call__(func)`` —
            see :meth:`Timer.__call__`.
        """
        return Timer(label=label or func.__name__)(func)

    return _decorator
