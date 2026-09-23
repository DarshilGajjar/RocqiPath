"""Shared behavior for every typed workflow configuration.

Configs are plain dataclasses that inherit `BaseConfig`. Their numpy
docstrings are the single source of documentation: `field_help` parses
the ``Parameters`` section so the CLI and Studio can show the same text the
API reference renders, without repeating it in field metadata.
"""

from __future__ import annotations

import dataclasses
import difflib
import inspect
import re
import sys
import types
import typing
from dataclasses import MISSING, asdict, fields, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Type, TypeVar

ConfigT = TypeVar("ConfigT", bound="BaseConfig")

#: Field metadata marking a setting most users never change. Generated
#: interfaces (CLI ``--help``, Studio forms) hide it behind "advanced".
ADVANCED = {"advanced": True}

#: Field metadata for settings that name local files or pass arbitrary
#: objects through to a backend. They stay available from Python and the
#: CLI but Studio never accepts them from the browser.
LOCAL_ONLY = {"advanced": True, "local_only": True}

#: Separator for nested overrides: ``valis__max_acceptable_error_um=5``.
NESTED_SEPARATOR = "__"


class BaseConfig:
    """Provide serialization, overrides and schema shared by every config."""

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseConfig":
        """Remember constructor arguments so `replace` can re-derive fields.

        Some fields are derived during validation (for example
        ``AlignConfig.filename_pattern`` from the role names, or
        ``ExtractPatchesConfig.stride`` from ``patch_size``). Replaying the
        original arguments keeps such fields in sync after a change.
        """
        instance = super().__new__(cls)
        names = [f.name for f in fields(cls) if f.init] if is_dataclass(cls) else []
        raw = dict(zip(names, args))
        raw.update(kwargs)
        object.__setattr__(instance, "_init_values", raw)
        return instance

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this config and nested dataclasses.

        Returns
        -------
        dict
            Recursively converted field names and values.

        Raises
        ------
        TypeError
            If a subclass is not a dataclass.
        """
        if not is_dataclass(self):
            raise TypeError("BaseConfig subclasses must be dataclasses")
        return asdict(self)

    @classmethod
    def from_dict(
        cls: Type[ConfigT],
        values: Mapping[str, Any],
    ) -> ConfigT:
        """Construct a config from declared dataclass fields.

        Nested configs may be given as dictionaries; they are converted to
        their declared config class.

        Parameters
        ----------
        values : mapping
            Field-name mapping passed to the dataclass constructor.

        Returns
        -------
        BaseConfig
            Instance of the concrete ``cls``.

        Raises
        ------
        TypeError
            If ``values`` contains an unknown field.
        """
        declared = {field.name for field in fields(cls) if field.init}
        unknown = sorted(set(values) - declared)
        if unknown:
            raise TypeError(_unknown_message(cls, unknown, declared))
        converted = dict(values)
        for name, nested_cls in nested_config_fields(cls).items():
            if isinstance(converted.get(name), Mapping):
                converted[name] = nested_cls.from_dict(converted[name])
        return cls(**converted)

    @classmethod
    def from_toml(cls: Type[ConfigT], path: str | Path) -> ConfigT:
        """Load a config from a TOML file whose keys are field names.

        Parameters
        ----------
        path : str or pathlib.Path
            TOML file. Nested configs are TOML tables, e.g. ``[valis]``.

        Returns
        -------
        BaseConfig
            Instance of the concrete ``cls``.
        """
        if sys.version_info >= (3, 11):
            import tomllib
        else:  # pragma: no cover - exercised on Python 3.10
            import tomli as tomllib
        with open(path, "rb") as stream:
            return cls.from_dict(tomllib.load(stream))

    def replace(self: ConfigT, **overrides: Any) -> ConfigT:
        """Return a copy with some fields changed and validation re-run.

        Parameters
        ----------
        **overrides
            Field values to change. Nested fields use a double underscore,
            for example ``valis__max_acceptable_error_um=5.0``.

        Returns
        -------
        BaseConfig
            A new, validated instance of the same class.

        Raises
        ------
        TypeError
            If a key names no field. The message suggests the closest name.
        """
        declared = {field.name for field in fields(self) if field.init}
        direct: Dict[str, Any] = {}
        nested: Dict[str, Dict[str, Any]] = {}
        for key, value in overrides.items():
            head, sep, rest = key.partition(NESTED_SEPARATOR)
            if sep and head in nested_config_fields(type(self)):
                nested.setdefault(head, {})[rest] = value
            elif key in declared:
                direct[key] = value
            else:
                raise TypeError(_unknown_message(type(self), [key], declared))
        for head, values in nested.items():
            current = direct.get(head, getattr(self, head))
            if isinstance(current, Mapping):
                current = nested_config_fields(type(self))[head].from_dict(current)
            direct[head] = current.replace(**values)
        recorded = getattr(self, "_init_values", None)
        if recorded is None:  # e.g. unpickled: fall back to current values
            recorded = {f.name: getattr(self, f.name) for f in fields(self) if f.init}
        values = dict(recorded)
        values.update(direct)
        return type(self).from_dict(values)

    def describe(self) -> list[tuple[str, Any]]:
        """Return display-ready fields in declaration order.

        Returns
        -------
        list of tuple of (str, object)
            Title-cased labels paired with current values.
        """
        return [
            (field.name.replace("_", " ").title(), getattr(self, field.name))
            for field in fields(self)
        ]


def _unknown_message(cls: type, unknown: List[str], declared: set) -> str:
    """Explain unknown field names, suggesting the closest declared ones."""
    parts = []
    for name in unknown:
        close = difflib.get_close_matches(name, sorted(declared), n=1)
        hint = f" (did you mean {close[0]!r}?)" if close else ""
        parts.append(f"{name!r}{hint}")
    return f"Unknown {cls.__name__} field(s): {', '.join(parts)}"


@lru_cache(maxsize=None)
def _type_hints(cls: type) -> Dict[str, Any]:
    module = sys.modules.get(cls.__module__)
    return typing.get_type_hints(cls, vars(module) if module else None)


def nested_config_fields(cls: type) -> Dict[str, Type["BaseConfig"]]:
    """Map each field holding a nested config to that config's class."""
    nested: Dict[str, Type[BaseConfig]] = {}
    for name, hint in _type_hints(cls).items():
        for candidate in (hint, *typing.get_args(hint)):
            if isinstance(candidate, type) and issubclass(candidate, BaseConfig):
                nested[name] = candidate
    return nested


_SECTION = re.compile(r"^(\w[\w ]*)\n-{3,}\s*$", re.M)
_ENTRY = re.compile(r"^(\w+(?:\s*,\s*\w+)*)\s*:\s*(.*)$")


def _parameters_section(doc: str) -> str:
    doc = inspect.cleandoc(doc or "")
    sections = list(_SECTION.finditer(doc))
    for index, match in enumerate(sections):
        if match.group(1).strip() == "Parameters":
            end = sections[index + 1].start() if index + 1 < len(sections) else len(doc)
            return doc[match.end() : end]
    return ""


def docstring_parameters(obj: Any) -> Dict[str, str]:
    """Parse the numpy ``Parameters`` section of any object's docstring."""
    return _parse_parameters(obj.__doc__ or "")


def _parse_parameters(doc: str) -> Dict[str, str]:
    help_text: Dict[str, List[str]] = {}
    current: List[str] = []
    for line in _parameters_section(doc).splitlines():
        entry = _ENTRY.match(line)
        if entry and not line.startswith((" ", "\t")):
            current = [name.strip() for name in entry.group(1).split(",")]
            for name in current:
                help_text[name] = []
        else:
            for name in current:
                help_text[name].append(line[4:] if line.startswith("    ") else line.strip())
    return {name: "\n".join(lines).strip() for name, lines in help_text.items()}


@lru_cache(maxsize=None)
def field_help(cls: type) -> Dict[str, str]:
    """Parse the numpy ``Parameters`` sections documenting a config's fields.

    Base classes are read first, so a subclass inherits the documentation of
    fields it does not redescribe. An entry may name several fields
    (``tif_tile, tif_pyramid : bool``).

    Parameters
    ----------
    cls : type
        Config class whose docstring documents each field.

    Returns
    -------
    dict
        Field name mapped to its full description, paragraphs separated
        by blank lines. Fields without documentation are absent.
    """
    merged: Dict[str, str] = {}
    for klass in reversed(cls.__mro__):
        if klass is object or "__doc__" not in vars(klass):
            continue
        merged.update(_parse_parameters(klass.__doc__))
    return merged


def summary_line(text: str) -> str:
    """Return the first paragraph of ``text`` as one line."""
    paragraph = text.strip().split("\n\n", 1)[0]
    return " ".join(paragraph.split())


def _is_union(origin: Any) -> bool:
    return origin is typing.Union or origin is getattr(types, "UnionType", None)


def _type_name(hint: Any) -> str:
    origin = typing.get_origin(hint)
    args = [a for a in typing.get_args(hint) if a is not type(None)]
    if origin is typing.Literal:
        return "choice"
    if _is_union(origin) and len(args) == 1:
        return _type_name(args[0])
    if origin in (list, tuple, List, typing.Tuple):
        return "list"
    if origin in (dict, Dict):
        return "mapping"
    if isinstance(hint, type) and issubclass(hint, BaseConfig):
        return "config"
    return {bool: "bool", int: "int", float: "float", str: "str"}.get(hint, "object")


def _item_info(hint: Any) -> Dict[str, Any]:
    """Element type (and fixed length for tuples) of a list-like field."""
    args = [a for a in typing.get_args(hint) if a is not type(None)]
    if _is_union(typing.get_origin(hint)) and len(args) == 1:
        hint = args[0]
    items = [a for a in typing.get_args(hint) if a is not Ellipsis]
    info: Dict[str, Any] = {"items": _type_name(items[0]) if items else "str"}
    if typing.get_origin(hint) is tuple and Ellipsis not in typing.get_args(hint):
        info["length"] = len(items)
    return info


def _choices(hint: Any, metadata: Mapping[str, Any]) -> list | None:
    if "choices" in metadata:
        return list(metadata["choices"])
    for candidate in (hint, *typing.get_args(hint)):
        if typing.get_origin(candidate) is typing.Literal:
            return list(typing.get_args(candidate))
    return None


def _default(field: dataclasses.Field) -> Any:
    if field.default is not MISSING:
        value = field.default
    elif field.default_factory is not MISSING:  # type: ignore[misc]
        value = field.default_factory()  # type: ignore[misc]
    else:
        return None
    if isinstance(value, BaseConfig):
        return value.to_dict()
    return value if isinstance(value, (str, int, float, bool, list, tuple, dict, type(None))) else None


def field_schema(cls: Type[BaseConfig]) -> List[Dict[str, Any]]:
    """Describe every field for generated interfaces (CLI flags, Studio forms).

    Parameters
    ----------
    cls : type
        A `BaseConfig` dataclass.

    Returns
    -------
    list of dict
        One entry per field with ``name``, ``type`` (``bool``, ``int``,
        ``float``, ``str``, ``choice``, ``list``, ``mapping``, ``config`` or
        ``object``), ``default``, ``required``, ``choices``, ``advanced``,
        ``local_only``,
        ``help`` (first paragraph) and ``doc`` (full description). Nested
        configs carry their own schema under ``fields``.
    """
    hints = _type_hints(cls)
    docs = field_help(cls)
    schema = []
    for field in fields(cls):
        if not field.init:
            continue
        hint = hints.get(field.name, Any)
        entry: Dict[str, Any] = {
            "name": field.name,
            "type": _type_name(hint),
            "default": _default(field),
            "required": field.default is MISSING and field.default_factory is MISSING,  # type: ignore[misc]
            "choices": _choices(hint, field.metadata),
            "advanced": bool(field.metadata.get("advanced", False)),
            "local_only": bool(field.metadata.get("local_only", False)),
            "help": summary_line(docs.get(field.name, "")),
            "doc": docs.get(field.name, ""),
        }
        if entry["type"] == "list":
            entry.update(_item_info(hint))
        if entry["type"] == "config":
            entry["fields"] = field_schema(nested_config_fields(cls)[field.name])
        schema.append(entry)
    return schema


__all__ = [
    "ADVANCED",
    "LOCAL_ONLY",
    "NESTED_SEPARATOR",
    "BaseConfig",
    "docstring_parameters",
    "field_help",
    "field_schema",
    "nested_config_fields",
    "summary_line",
]
