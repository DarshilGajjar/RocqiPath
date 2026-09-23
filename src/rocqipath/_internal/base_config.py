"""Shared serialization and display behavior for typed configurations."""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from typing import Any, Dict, Type, TypeVar

ConfigT = TypeVar("ConfigT", bound="BaseConfig")


class BaseConfig:
    """Provide serialization shared by every typed pipeline config."""

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
        values: Dict[str, Any],
    ) -> ConfigT:
        """Construct a config from declared dataclass fields.

        Parameters
        ----------
        values : dict
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
            joined = ", ".join(unknown)
            raise TypeError(f"Unknown {cls.__name__} field(s): {joined}")
        return cls(**values)

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


__all__ = ["BaseConfig"]
