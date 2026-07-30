"""Deprecated compatibility path for the registration engine.

Use :mod:`rocqipath.registration.registrar` for new code.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "rocqipath.registration.core is deprecated; "
    "import ValisConfig and WSIRegistrar from rocqipath.registration.registrar instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .registrar import ValisConfig, WSIRegistrar  # noqa: E402

__all__ = ["ValisConfig", "WSIRegistrar"]
