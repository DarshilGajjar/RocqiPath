"""What Studio offers and accepts, derived from the workflow registry.

Studio shows every registered workflow with a form generated from its config
schema. Only plain settings are offered: fields marked ``local_only`` (file
paths, raw backend keyword arguments, class objects) stay out of the
browser, and every submission is validated by constructing the real config.
"""

from __future__ import annotations

from typing import Any, Dict, List

from rocqipath._internal.base_config import docstring_parameters, field_schema, summary_line
from rocqipath.extras import missing_modules
from rocqipath.registry import Workflow, get_workflow, list_workflows

#: Settings whose value enables a backend needing another extra.
_BACKEND_EXTRAS = {
    ("align", "backend", "valis"): "valis",
    ("extract_tissue", "detector", "semantic"): "semantic",
    ("extract_tma", "detector", "semantic"): "semantic",
}


def _browser_fields(schema: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fields = []
    for entry in schema:
        if entry["local_only"] or entry["type"] == "object":
            continue
        if entry["type"] == "config":
            entry = {**entry, "fields": _browser_fields(entry["fields"])}
        fields.append(entry)
    return fields


def describe(workflow: Workflow) -> Dict[str, Any]:
    """Describe one workflow for the Studio interface."""
    missing = missing_modules(workflow.extra)
    documented = docstring_parameters(workflow.function)
    return {
        "name": workflow.name,
        "label": workflow.name.replace("_", " ").capitalize(),
        "summary": workflow.summary,
        "extra": workflow.extra,
        "available": not missing,
        "missing": missing,
        "inputs": {"kind": workflow.inputs.kind, "help": summary_line(documented.get("inputs", ""))},
        "options": [
            {"name": option, "help": summary_line(documented.get(option, ""))}
            for option in workflow.options
        ],
        "settings": _browser_fields(field_schema(workflow.config)),
    }


def catalog() -> List[Dict[str, Any]]:
    """Describe every registered workflow."""
    return [describe(workflow) for workflow in list_workflows()]


def _allowed(schema: List[Dict[str, Any]], prefix: str = "") -> set:
    names = set()
    for entry in schema:
        if entry["type"] == "config":
            names |= _allowed(entry["fields"], f"{prefix}{entry['name']}__")
        else:
            names.add(prefix + entry["name"])
    return names


def build_config(workflow: Workflow, settings: Dict[str, Any]):
    """Construct the workflow's config from browser settings."""
    direct = {k: v for k, v in settings.items() if "__" not in k}
    nested = {k: v for k, v in settings.items() if "__" in k}
    config = workflow.config.from_dict(direct)
    return config.replace(**nested) if nested else config


def validate(name: str, settings: Dict[str, Any], options: List[str]) -> Workflow:
    """Check a submission and return its workflow.

    Raises
    ------
    KeyError
        Unknown workflow.
    ValueError
        A setting or option Studio does not accept, or a config that fails
        validation.
    RuntimeError
        The workflow (or the chosen backend) needs an extra that is not
        installed.
    """
    workflow = get_workflow(name)
    allowed = _allowed(_browser_fields(field_schema(workflow.config)))
    rejected = sorted(set(settings) - allowed)
    if rejected:
        raise ValueError(f"Studio does not accept these settings: {', '.join(rejected)}")
    unknown = sorted(set(options) - set(workflow.options))
    if unknown:
        raise ValueError(f"{workflow.name} has no option(s): {', '.join(unknown)}")
    missing = missing_modules(workflow.extra)
    if missing:
        raise RuntimeError(f"Install rocqipath[{workflow.extra}] (missing: {', '.join(missing)})")
    for (target, field, value), extra in _BACKEND_EXTRAS.items():
        if target == workflow.name and settings.get(field) == value and missing_modules(extra):
            raise RuntimeError(f"Install rocqipath[{extra}] to use {field}={value!r}")
    try:
        build_config(workflow, settings)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    return workflow


__all__ = ["build_config", "catalog", "describe", "validate"]
