"""Reusable interactive-input helpers for RocqiPath commands."""

from __future__ import annotations

import os
from typing import List, Optional


def _get_existing_dir(prompt: str) -> str:
    """Prompt for a directory path that must already exist.

    Blocks in a loop until a non-empty path is entered that resolves
    (after quote-stripping, ``~`` expansion, and absolute-path
    resolution) to an existing directory, or the user declines to retry.

    Parameters
    ----------
    prompt : str
        The prompt text shown to the user (including any trailing
        ``": "`` — not added automatically by this function).

    Returns
    -------
    str
        The resolved absolute path of the validated, existing directory.

    Raises
    ------
    SystemExit
        If the entered path doesn't exist and the user answers anything
        other than ``"y"`` when asked whether to retry.
    """
    while True:
        raw = input(prompt).strip().replace('"', "").replace("'", "")
        if not raw:
            print("  Path cannot be empty.")
            continue
        p = os.path.abspath(os.path.expanduser(raw))
        if os.path.isdir(p):
            return p
        print(f"  Directory not found: {p}")
        if input("  Retry? (y/n): ").strip().lower() != "y":
            raise SystemExit("Cancelled.")


def _get_dir(prompt: str) -> str:
    """Prompt for a directory path, creating it if it doesn't already exist.

    Unlike :func:`_get_existing_dir`, this is for *output* directories —
    a missing path is not an error, it's simply created.

    Parameters
    ----------
    prompt : str
        The prompt text shown to the user.

    Returns
    -------
    str
        The resolved absolute path of the (now-existing) directory.
    """
    while True:
        raw = input(prompt).strip().replace('"', "").replace("'", "")
        if not raw:
            print("  Path cannot be empty.")
            continue
        p = os.path.abspath(os.path.expanduser(raw))
        os.makedirs(p, exist_ok=True)
        return p


def _get_int(prompt: str, default: int, min_val: int = 0) -> int:
    """Prompt for an integer, showing and accepting a default on empty input.

    Parameters
    ----------
    prompt : str
        The prompt text; the default value is appended automatically in
        ``[brackets]``.
    default : int
        Value returned if the user presses Enter without typing
        anything.
    min_val : int, optional
        Minimum acceptable value (inclusive). Defaults to ``0``. Input
        below this re-prompts rather than raising.

    Returns
    -------
    int
        The validated integer — either ``default`` (on empty input) or
        the user's entered value, guaranteed ``>= min_val``.

    Notes
    -----
    Non-numeric input and values below ``min_val`` both re-prompt with
    an explanatory message rather than raising, so a typo never crashes
    the interactive session.
    """
    while True:
        raw = input(f"  {prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if val < min_val:
                print(f"  Value must be >= {min_val}.")
                continue
            return val
        except ValueError:
            print("  Please enter a valid integer.")


def _get_float(prompt: str, default: float) -> float:
    """Prompt for a float, showing and accepting a default on empty input.

    Parameters
    ----------
    prompt : str
        The prompt text; the default value is appended automatically in
        ``[brackets]``.
    default : float
        Value returned if the user presses Enter without typing
        anything.

    Returns
    -------
    float
        The validated float — either ``default`` (on empty input) or the
        user's entered value.

    Notes
    -----
    Non-numeric input re-prompts with an explanatory message rather than
    raising. Unlike :func:`_get_int`, there is no minimum-value check
    here — any parseable float is accepted.
    """
    while True:
        raw = input(f"  {prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a valid number.")


def _get_bool(prompt: str, default: bool) -> bool:
    """Prompt for a yes/no answer, showing and accepting a default on empty input.

    Parameters
    ----------
    prompt : str
        The prompt text; a ``[y]`` or ``[n]`` hint (matching ``default``)
        is appended automatically.
    default : bool
        Value returned if the user presses Enter without typing
        anything.

    Returns
    -------
    bool
        ``default`` on empty input; otherwise ``True`` if the
        (lowercased) response is one of ``"y"``, ``"yes"``, ``"1"``, or
        ``"true"``, and ``False`` for any other non-empty input
        (including typos — there is no re-prompt loop here, unlike the
        other ``_get_*`` helpers, so an unrecognised response is
        silently treated as "no").
    """
    d_str = "y" if default else "n"
    raw = input(f"  {prompt} [{d_str}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def _get_optional_float(prompt: str) -> Optional[float]:
    """Prompt for an optional float, where empty or "none" both mean "unset".

    Parameters
    ----------
    prompt : str
        The prompt text; a ``[none]`` hint is appended automatically.

    Returns
    -------
    float or None
        ``None`` if the input is empty or (case-insensitively) the
        literal word ``"none"``, or if the input cannot be parsed as a
        float (invalid input is treated as "unset" rather than
        re-prompting, unlike most of the other ``_get_*`` helpers).
        Otherwise, the parsed float value.
    """
    raw = input(f"  {prompt} [none]: ").strip()
    if not raw or raw.lower() == "none":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _get_stain_list(prompt: str) -> List[str]:
    """Prompt for a comma-separated list of stain/biomarker labels.

    Parameters
    ----------
    prompt : str
        The prompt text; an ``[all]`` hint is appended automatically.

    Returns
    -------
    list of str
        ``["all"]`` if the input is empty or (case-insensitively) the
        literal word ``"all"`` — the convention used throughout this
        package's pipelines to mean "don't filter by stain, process
        everything". Otherwise, the comma-separated input split into
        individual labels, each stripped of surrounding whitespace, with
        empty entries (e.g. from trailing commas) dropped.
    """
    raw = input(f"  {prompt} [all]: ").strip()
    if not raw or raw.lower() == "all":
        return ["all"]
    return [s.strip() for s in raw.split(",") if s.strip()]
