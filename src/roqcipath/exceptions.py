"""
roqcipath.exceptions
=========================
Custom exception hierarchy for ``roqcipath``.

All library-specific errors inherit from :class:`WSIProcessingError` so
callers can catch every error the library raises with a single ``except``
clause::

    from roqcipath.exceptions import WSIProcessingError

    try:
        run_alignment(cfg)
    except WSIProcessingError as exc:
        logger.error("Pipeline failed: %s", exc)

Hierarchy
---------
::

    WSIProcessingError
    ├── ConfigurationError          bad or missing config values
    ├── SlideNotFoundError          a WSI path does not exist
    ├── UnsupportedFormatError      format OpenSlide cannot read
    ├── RegistrationError           alignment / VALIS failure
    │   └── RegistrationQualityError   error exceeds threshold
    ├── ExtractionError             core or patch extraction failure
    └── DependencyError             optional dependency not installed
"""

from __future__ import annotations

__all__ = [
    "WSIProcessingError",
    "ConfigurationError",
    "SlideNotFoundError",
    "UnsupportedFormatError",
    "RegistrationError",
    "RegistrationQualityError",
    "ExtractionError",
    "DependencyError",
]


class WSIProcessingError(Exception):
    """Base class for all ``roqcipath`` exceptions."""


class ConfigurationError(WSIProcessingError):
    """Raised when a configuration value is missing, invalid, or inconsistent.

    Examples
    --------
    >>> raise ConfigurationError("patch_size must be a positive integer")
    """


class SlideNotFoundError(WSIProcessingError, FileNotFoundError):
    """Raised when a WSI file path does not exist on disk.

    Inherits from :class:`FileNotFoundError` so existing code that catches
    the built-in also catches this.
    """


class UnsupportedFormatError(WSIProcessingError):
    """Raised when a file extension is not a recognised WSI format or cannot
    be opened by the available backend (e.g. OpenSlide, pyvips)."""


class RegistrationError(WSIProcessingError):
    """Raised when slide registration fails to produce a valid transform."""


class RegistrationQualityError(RegistrationError):
    """Raised when registration succeeds but the measured error exceeds the
    configured ``max_acceptable_error_um`` threshold."""

    def __init__(self, error_um: float, threshold_um: float) -> None:
        """Build the exception and format a human-readable message.

        Parameters
        ----------
        error_um : float
            The measured registration error, in micrometres, that
            triggered this failure (e.g. mean landmark displacement or
            target registration error).
        threshold_um : float
            The configured ``max_acceptable_error_um`` threshold that
            ``error_um`` exceeded.

        Attributes
        ----------
        error_um : float
            Stored verbatim from the parameter, for programmatic
            inspection by callers (e.g. logging, retry logic, QC reports).
        threshold_um : float
            Stored verbatim from the parameter.

        Notes
        -----
        The formatted message (both values to two decimal places) is
        passed to :class:`Exception`'s constructor, so ``str(exc)`` and
        default tracebacks already contain a readable summary — callers
        do not need to re-format ``error_um``/``threshold_um`` themselves.
        """
        self.error_um = error_um
        self.threshold_um = threshold_um
        super().__init__(
            f"Registration error {error_um:.2f} µm exceeds threshold "
            f"{threshold_um:.2f} µm."
        )


class ExtractionError(WSIProcessingError):
    """Raised when patch or core extraction fails for a slide."""


class DependencyError(WSIProcessingError, ImportError):
    """Raised when an optional dependency required for the requested operation
    is not installed.

    Inherits from :class:`ImportError` so existing ``except ImportError``
    clauses continue to work.

    Examples
    --------
    >>> raise DependencyError("valis", "pip install roqcipath[valis]")
    """

    def __init__(self, package: str, install_hint: str = "") -> None:
        """Build the exception and format a human-readable message.

        Parameters
        ----------
        package : str
            Name of the missing optional dependency (e.g. ``"tiatoolbox"``,
            ``"valis"``, ``"pyvips"``). Used verbatim in the error message
            and stored on the instance for programmatic inspection.
        install_hint : str, optional
            A copy-pasteable install command shown to the user, e.g.
            ``"pip install roqcipath[stain]"``. When omitted, the message
            simply states that the dependency is missing without
            suggesting how to fix it.

        Attributes
        ----------
        package : str
            Stored verbatim from the parameter.

        Notes
        -----
        Because this class also inherits from :class:`ImportError`, any
        pre-existing ``except ImportError:`` guard elsewhere in a caller's
        code (including this library's own optional-dependency guards)
        will catch it without modification.
        """
        self.package = package
        hint = f"  Install with: {install_hint}" if install_hint else ""
        super().__init__(
            f"Optional dependency '{package}' is not installed.{hint}"
        )
