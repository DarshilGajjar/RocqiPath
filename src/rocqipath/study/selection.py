"""Selections: post-processing expressed as a view, not a re-computation.

A selection is a named, saved rule evaluated over a stage manifest.  It stores
the matching artifact identifiers, the rule text, the recipe hash, and a
timestamp — but it never moves a pixel.

This is the practical difference from baking ``tissue_threshold=0.5`` into
extraction.  Changing the threshold produces a new selection in seconds, both
selections remain on disk, and a methods section can name exactly which one
produced a figure.

Rule language
-------------
A small, deliberately boring expression language, evaluated through a
whitelisted AST walk rather than :func:`eval`:

* manifest fields by name — ``tissue_fraction``, ``blur``, ``stain``
* comparisons and chaining — ``0.4 <= tissue_fraction < 0.9``
* boolean logic — ``and``, ``or``, ``not``
* membership — ``stain in ["cd8", "cd31"]``
* arithmetic — ``+``, ``-``, ``*``, ``/``
* helpers — ``percentile("blur", 10)``, ``is_null(x)``, ``lower(x)``

Example::

    tissue_fraction >= 0.6 and blur >= percentile("blur", 10)
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.core.output import safe_name

__all__ = [
    "Selection",
    "RuleError",
    "build_selection",
    "evaluate_rule",
    "load_selection",
    "rule_from_thresholds",
]


class RuleError(ConfigurationError):
    """Raised when a selection rule cannot be parsed or evaluated."""


_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.UnaryOp,
    ast.BinOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Call,
    ast.And,
    ast.Or,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.IfExp,
)


def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    """Return the linear-interpolated ``q``-th percentile of ``values``."""
    numbers = sorted(
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0]
    position = (max(0.0, min(100.0, float(q))) / 100.0) * (len(numbers) - 1)
    lower = int(position)
    upper = min(lower + 1, len(numbers) - 1)
    weight = position - lower
    return numbers[lower] * (1.0 - weight) + numbers[upper] * weight


class _RuleEvaluator(ast.NodeVisitor):
    """Evaluate one parsed rule against a single manifest row."""

    def __init__(self, row: Mapping[str, Any], helpers: Mapping[str, Callable[..., Any]]) -> None:
        """Bind the row and helper functions this evaluation may use."""
        self.row = row
        self.helpers = helpers

    def generic_visit(self, node: ast.AST) -> Any:
        """Reject any node type not on the whitelist.

        Raises
        ------
        RuleError
            Always, for disallowed syntax.
        """
        raise RuleError(
            f"Unsupported expression element: {type(node).__name__}. "
            "Selection rules allow comparisons, and/or/not, arithmetic, "
            "membership tests, and the percentile/is_null/lower helpers."
        )

    def visit(self, node: ast.AST) -> Any:
        """Dispatch after confirming the node type is allowed."""
        if not isinstance(node, _ALLOWED_NODES):
            self.generic_visit(node)
        return super().visit(node)

    def visit_Expression(self, node: ast.Expression) -> Any:  # noqa: N802 - ast API
        """Evaluate the wrapped expression body."""
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:  # noqa: N802 - ast API
        """Return a literal value."""
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:  # noqa: N802 - ast API
        """Resolve a bare name to a manifest field, ``True``/``False``, or ``None``."""
        if node.id in ("True", "False", "None"):  # pragma: no cover - Python parses as Constant
            return {"True": True, "False": False, "None": None}[node.id]
        return self.row.get(node.id)

    def visit_List(self, node: ast.List) -> Any:  # noqa: N802 - ast API
        """Evaluate a list literal."""
        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> Any:  # noqa: N802 - ast API
        """Evaluate a tuple literal."""
        return tuple(self.visit(item) for item in node.elts)

    def visit_Set(self, node: ast.Set) -> Any:  # noqa: N802 - ast API
        """Evaluate a set literal."""
        return {self.visit(item) for item in node.elts}

    def visit_IfExp(self, node: ast.IfExp) -> Any:  # noqa: N802 - ast API
        """Evaluate a conditional expression."""
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:  # noqa: N802 - ast API
        """Evaluate ``and`` / ``or`` with short-circuit semantics."""
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not self.visit(value):
                    return False
            return True
        for value in node.values:
            if self.visit(value):
                return True
        return False

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:  # noqa: N802 - ast API
        """Evaluate unary ``not``, ``-``, and ``+``."""
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not operand
        if operand is None:
            return None
        return -operand if isinstance(node.op, ast.USub) else +operand

    def visit_BinOp(self, node: ast.BinOp) -> Any:  # noqa: N802 - ast API
        """Evaluate binary arithmetic, returning ``None`` on missing operands."""
        left, right = self.visit(node.left), self.visit(node.right)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right if right else None
            if isinstance(node.op, ast.Mod):
                return left % right if right else None
        except TypeError as exc:
            raise RuleError(f"Cannot combine {left!r} and {right!r}: {exc}") from exc
        raise RuleError(f"Unsupported operator: {type(node.op).__name__}")

    def visit_Compare(self, node: ast.Compare) -> Any:  # noqa: N802 - ast API
        """Evaluate a comparison chain, treating missing fields as non-matching."""
        left = self.visit(node.left)
        for operator, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if isinstance(operator, ast.In):
                if right is None or left not in right:
                    return False
                left = right
                continue
            if isinstance(operator, ast.NotIn):
                if right is None or left in right:
                    return False
                left = right
                continue
            if isinstance(operator, ast.Eq):
                if left != right:
                    return False
                left = right
                continue
            if isinstance(operator, ast.NotEq):
                if left == right:
                    return False
                left = right
                continue
            if left is None or right is None:
                return False
            try:
                if isinstance(operator, ast.Lt) and not left < right:
                    return False
                if isinstance(operator, ast.LtE) and not left <= right:
                    return False
                if isinstance(operator, ast.Gt) and not left > right:
                    return False
                if isinstance(operator, ast.GtE) and not left >= right:
                    return False
            except TypeError:
                return False
            left = right
        return True

    def visit_Call(self, node: ast.Call) -> Any:  # noqa: N802 - ast API
        """Evaluate a whitelisted helper call."""
        if not isinstance(node.func, ast.Name) or node.func.id not in self.helpers:
            allowed = ", ".join(sorted(self.helpers))
            raise RuleError(f"Only these helpers may be called in a rule: {allowed}.")
        if node.keywords:
            raise RuleError("Rule helpers do not take keyword arguments.")
        return self.helpers[node.func.id](*[self.visit(arg) for arg in node.args])


def _build_helpers(records: Sequence[Mapping[str, Any]]) -> Dict[str, Callable[..., Any]]:
    """Return rule helpers bound to the manifest being evaluated."""
    cache: Dict[tuple, Optional[float]] = {}

    def percentile(field_name: Any, q: Any = 50) -> Optional[float]:
        """Return the ``q``-th percentile of one field across the manifest."""
        key = (str(field_name), float(q))
        if key not in cache:
            cache[key] = _percentile([row.get(str(field_name)) for row in records], float(q))
        return cache[key]

    def is_null(value: Any) -> bool:
        """Return whether a value is missing."""
        return value is None

    def lower(value: Any) -> Any:
        """Lowercase a string value, passing other types through."""
        return value.lower() if isinstance(value, str) else value

    return {"percentile": percentile, "is_null": is_null, "lower": lower}


def evaluate_rule(
    rule: str,
    records: Sequence[Mapping[str, Any]],
) -> List[Mapping[str, Any]]:
    """Return the manifest rows matching ``rule``.

    Parameters
    ----------
    rule : str
        Expression in the selection rule language.  An empty rule matches
        every row.
    records : sequence of Mapping
        Manifest rows to filter.

    Returns
    -------
    list of Mapping
        Matching rows, in input order.

    Raises
    ------
    RuleError
        If the rule cannot be parsed or uses disallowed syntax.
    """
    text = (rule or "").strip()
    if not text:
        return list(records)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise RuleError(f"Could not parse rule {text!r}: {exc.msg}") from exc
    helpers = _build_helpers(records)
    matched: List[Mapping[str, Any]] = []
    for row in records:
        if bool(_RuleEvaluator(row, helpers).visit(tree)):
            matched.append(row)
    return matched


def rule_from_thresholds(**thresholds: float) -> str:
    """Compose a rule from keyword minimum thresholds.

    Parameters
    ----------
    **thresholds : float
        Field name mapped to its inclusive minimum.

    Returns
    -------
    str
        A rule such as ``"tissue_fraction >= 0.6 and blur >= 12"``.

    Examples
    --------
    >>> rule_from_thresholds(tissue_fraction=0.6)
    'tissue_fraction >= 0.6'
    """
    parts = [f"{name} >= {value!r}" for name, value in sorted(thresholds.items())]
    return " and ".join(parts)


@dataclass
class Selection:
    """A named, saved QC view over one stage manifest.

    Attributes
    ----------
    name : str
        Selection name, used as its filename.
    study : str
        Study the selection belongs to.
    stage : str
        Stage whose manifest was filtered.
    rule : str
        Rule text evaluated to produce this selection.
    manifest : str
        Manifest path the rule was evaluated over.
    recipe_hash : str
        Recipe under which the manifest was produced.
    created_at : str
        UTC timestamp.
    n_input, n_selected : int
        Rows considered and rows kept.
    uids : list of str
        Identifiers of the selected artifacts.
    stats : dict
        Per-field summary statistics of the selected rows.
    """

    name: str
    study: str
    stage: str
    rule: str
    manifest: str = ""
    recipe_hash: str = ""
    created_at: str = ""
    n_input: int = 0
    n_selected: int = 0
    uids: List[str] = field(default_factory=list)
    stats: Dict[str, Dict[str, float]] = field(default_factory=dict)

    @property
    def fraction_kept(self) -> float:
        """Return the proportion of input rows retained."""
        return 0.0 if not self.n_input else self.n_selected / self.n_input

    def contains(self, uid: str) -> bool:
        """Return whether ``uid`` is part of this selection."""
        return uid in set(self.uids)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this selection."""
        return {
            "name": self.name,
            "study": self.study,
            "stage": self.stage,
            "rule": self.rule,
            "manifest": self.manifest,
            "recipe_hash": self.recipe_hash,
            "created_at": self.created_at,
            "n_input": self.n_input,
            "n_selected": self.n_selected,
            "stats": self.stats,
            "uids": self.uids,
        }

    def write(self, directory: Path) -> Path:
        """Write ``<directory>/<name>.json`` and return the path."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe_name(self.name)}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Selection":
        """Rebuild a selection from its serialised form."""
        return cls(
            name=str(data.get("name", "")),
            study=str(data.get("study", "")),
            stage=str(data.get("stage", "")),
            rule=str(data.get("rule", "")),
            manifest=str(data.get("manifest", "")),
            recipe_hash=str(data.get("recipe_hash", "")),
            created_at=str(data.get("created_at", "")),
            n_input=int(data.get("n_input", 0)),
            n_selected=int(data.get("n_selected", 0)),
            uids=list(data.get("uids", [])),
            stats=dict(data.get("stats", {})),
        )


def build_selection(
    name: str,
    records: Sequence[Mapping[str, Any]],
    rule: str,
    *,
    study: str = "",
    stage: str = "",
    manifest: str = "",
    recipe_hash: str = "",
    uid_field: str = "uid",
    stat_fields: Sequence[str] = (),
) -> Selection:
    """Evaluate ``rule`` over ``records`` and package the result.

    Parameters
    ----------
    name : str
        Selection name.
    records : sequence of Mapping
        Manifest rows.
    rule : str
        Rule text.  Empty selects everything.
    study, stage, manifest, recipe_hash : str, optional
        Provenance carried into the saved selection.
    uid_field : str, default "uid"
        Field holding each artifact's identifier.
    stat_fields : sequence of str, optional
        Numeric fields to summarise over the selected rows.

    Returns
    -------
    Selection
        Populated selection, not yet written to disk.
    """
    from rocqipath.study.manifests import summarise_field

    matched = evaluate_rule(rule, records)
    stats: Dict[str, Dict[str, float]] = {}
    for name_of_field in stat_fields:
        summary = summarise_field(matched, name_of_field)
        if summary:
            stats[name_of_field] = summary
    return Selection(
        name=name,
        study=study,
        stage=stage,
        rule=(rule or "").strip(),
        manifest=manifest,
        recipe_hash=recipe_hash,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        n_input=len(records),
        n_selected=len(matched),
        uids=[str(row.get(uid_field)) for row in matched if row.get(uid_field) is not None],
        stats=stats,
    )


def load_selection(path: Path) -> Selection:
    """Read a saved selection.

    Parameters
    ----------
    path : pathlib.Path
        Selection JSON path.

    Returns
    -------
    Selection
        Parsed selection.

    Raises
    ------
    ConfigurationError
        If the file is missing or malformed.
    """
    selection_path = Path(path)
    if not selection_path.is_file():
        raise ConfigurationError(f"No selection at {selection_path}.")
    try:
        return Selection.from_dict(json.loads(selection_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{selection_path} is not valid JSON: {exc}") from exc
