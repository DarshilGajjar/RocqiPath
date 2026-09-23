"""The workflow registry behind ``rp.<workflow>()``, the CLI and Studio.

Every workflow is an ordinary function decorated with `workflow`. The
decorator gives all workflows the same calling convention::

    result = rp.<name>(inputs, output_dir, *, config=None, **overrides)

and records the workflow in `WORKFLOWS`, which the command line and
Studio read to build their commands and forms. Adding a workflow therefore
means writing one decorated function; see ``docs/contributing``.

The decorator handles, for every workflow:

* building the config from ``config`` plus keyword ``overrides``
  (``valis__max_acceptable_error_um=5`` reaches a nested field) and
  rejecting unknown keywords with a suggestion;
* passing extra keyword arguments the workflow declares (such as
  ``compare_to=``) through to the function;
* resolving ``inputs`` (paths, earlier results, or output folders) into
  `Item` objects, checking that each exists;
* creating ``output_dir``, recording the run in ``rocqipath.json`` there,
  and returning a `Result`.
"""

from __future__ import annotations

import dataclasses
import difflib
import functools
import inspect
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Type

from rocqipath._internal.base_config import BaseConfig, summary_line


@dataclass(frozen=True)
class Item:
    """One file a workflow produced, described well enough to feed the next.

    Parameters
    ----------
    sample_id : str
        Patient, block, core or slide identifier the file belongs to.
    role : str
        What the file is, e.g. ``"region"``, ``"core"``, ``"aligned"``,
        ``"reference"``, ``"patch"``, ``"normalized"``, ``"weights"``,
        ``"count"`` or ``"figure"``.
    path : pathlib.Path
        Absolute path to the file or folder.
    magnification : float, optional
        Objective magnification of the pixels in ``path``, when known.
    source : pathlib.Path, optional
        Input file this item was derived from.
    meta : dict
        Workflow-specific details (region boxes, stain, patch IDs, ...).
    """

    sample_id: str
    role: str
    path: Path
    magnification: Optional[float] = None
    source: Optional[Path] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Result:
    """What a workflow run produced.

    Iterating a result yields its `Item` objects. ``summary`` holds
    the workflow's own numbers, such as region counts or cell counts.

    Parameters
    ----------
    workflow : str
        Registered workflow name.
    output_dir : pathlib.Path
        Folder the workflow wrote into.
    items : tuple of Item
        Every produced file, in a stable order.
    summary : dict
        Workflow-specific results; documented on each workflow.
    config : BaseConfig or None
        The exact settings used (``None`` when read back from a manifest
        of an unregistered workflow).
    manifest_path : pathlib.Path, optional
        The run manifest describing this result on disk, when written.
    """

    workflow: str
    output_dir: Path
    items: Tuple[Item, ...]
    summary: Dict[str, Any]
    config: Optional[BaseConfig]
    manifest_path: Optional[Path] = None

    def by_role(self, role: str) -> List[Item]:
        """Return the items whose ``role`` equals ``role``."""
        return [item for item in self.items if item.role == role]

    def __iter__(self) -> Iterator[Item]:
        """Iterate over produced items."""
        return iter(self.items)

    def __len__(self) -> int:
        """Return the number of produced items."""
        return len(self.items)


@dataclass(frozen=True)
class InputSpec:
    """Describe what a workflow accepts as ``inputs``.

    Parameters
    ----------
    kind : str
        Human-readable description used in help text, e.g.
        ``"whole-slide images"``.
    roles : tuple of str
        Item roles accepted from a previous workflow's output.
    """

    kind: str = "files"
    roles: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Workflow:
    """A registered workflow.

    Parameters
    ----------
    name : str
        Registry and command name (``extract_tissue``).
    function : callable
        The public function users call.
    config : type
        Its `rocqipath._internal.base_config.BaseConfig` class.
    extra : str
        The ``pip install rocqipath[<extra>]`` extra it needs.
    inputs : InputSpec
        What ``inputs`` may contain.
    options : tuple of str
        Extra keyword arguments besides config fields (e.g. ``compare_to``).
    """

    name: str
    function: Callable[..., Result]
    config: Type[BaseConfig]
    extra: str
    inputs: InputSpec
    options: Tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        """First line of the workflow's docstring."""
        return summary_line(inspect.getdoc(self.function) or "")

    @property
    def cli_name(self) -> str:
        """Command-line spelling of the name (``extract-tissue``)."""
        return self.name.replace("_", "-")


#: All registered workflows, keyed by name, in registration order.
WORKFLOWS: Dict[str, Workflow] = {}

Implementation = Callable[..., Tuple[Sequence[Item], Dict[str, Any]]]


def _default_config(config_class: Type[BaseConfig], overrides: Dict[str, Any]) -> BaseConfig:
    """Build a config, taking required fields from ``overrides`` when needed."""
    required = [
        f.name for f in fields(config_class)
        if f.init and f.default is MISSING and f.default_factory is MISSING  # type: ignore[misc]
    ]
    missing = [name for name in required if name not in overrides]
    if missing:
        raise TypeError(
            f"{config_class.__name__} has no default for {', '.join(missing)}; pass "
            f"config={config_class.__name__}(...) or give them as keyword arguments"
        )
    return config_class.from_dict({name: overrides.pop(name) for name in required})


def workflow(
    name: str,
    *,
    config: Type[BaseConfig],
    extra: str,
    inputs: InputSpec = InputSpec(),
) -> Callable[[Implementation], Callable[..., Result]]:
    """Register a function as a workflow with the standard calling convention.

    The decorated function receives ``(inputs, output_dir, config, **options)``
    where ``inputs`` is a list of `Item` (see
    `rocqipath.io.inputs.resolve_inputs`), ``output_dir`` an existing
    `pathlib.Path` and ``config`` a validated config instance. It
    returns ``(items, summary)``. Keyword-only parameters of the decorated
    function (other than ``config``) become the workflow's extra options.

    Parameters
    ----------
    name : str
        Unique registry name, also used as the CLI command.
    config : type
        Config dataclass for this workflow.
    extra : str
        Name of the optional-dependency extra the workflow needs.
    inputs : InputSpec, optional
        Accepted inputs.

    Returns
    -------
    callable
        Decorator producing the public function.
    """

    def decorate(implementation: Implementation) -> Callable[..., Result]:
        signature = inspect.signature(implementation)
        options = tuple(
            parameter.name
            for parameter in signature.parameters.values()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.name != "config"
        )
        field_names = {f.name for f in fields(config) if f.init}

        @functools.wraps(implementation)
        def public(inputs, output_dir, *, config=None, **overrides) -> Result:
            passed = {key: overrides.pop(key) for key in list(overrides) if key in options}
            unknown = [
                key for key in overrides
                if key not in field_names and key.split("__", 1)[0] not in field_names
            ]
            if unknown:
                close = difflib.get_close_matches(unknown[0], sorted(field_names | set(options)), n=1)
                hint = f" (did you mean {close[0]!r}?)" if close else ""
                raise TypeError(f"{name}() got an unexpected keyword {unknown[0]!r}{hint}")
            chosen = config if config is not None else _default_config(config_class, overrides)
            if not isinstance(chosen, config_class):
                raise TypeError(
                    f"{name} expects config={config_class.__name__}, got {type(chosen).__name__}"
                )
            if overrides:
                chosen = chosen.replace(**overrides)
            out = Path(output_dir).expanduser().resolve()
            out.mkdir(parents=True, exist_ok=True)
            from rocqipath.io.inputs import resolve_inputs
            from rocqipath.io.manifest import write_run_manifest

            try:
                resolved = resolve_inputs(inputs, input_spec.roles)
            except FileNotFoundError as exc:
                raise FileNotFoundError(f"{name}: {exc}") from None
            items, summary = implementation(resolved, out, config=chosen, **passed)
            result = Result(
                workflow=name,
                output_dir=out,
                items=tuple(items),
                summary=dict(summary),
                config=chosen,
            )
            manifest = write_run_manifest(result, [item.path for item in resolved])
            return dataclasses.replace(result, manifest_path=manifest)

        config_class = config
        input_spec = inputs
        public.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
            [
                inspect.Parameter("inputs", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                inspect.Parameter("output_dir", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                inspect.Parameter("config", inspect.Parameter.KEYWORD_ONLY, default=None),
                *[signature.parameters[o] for o in options],
                inspect.Parameter("overrides", inspect.Parameter.VAR_KEYWORD),
            ],
            return_annotation="Result",
        )
        if name in WORKFLOWS:
            raise ValueError(f"workflow {name!r} is already registered")
        WORKFLOWS[name] = Workflow(name, public, config, extra, inputs, options)
        return public

    return decorate


def list_workflows() -> List[Workflow]:
    """Return every registered workflow in registration order.

    Returns
    -------
    list of Workflow
        Name, summary, config class, required extra and accepted inputs.
    """
    import rocqipath.api  # noqa: F401  (registers the built-in workflows)

    return list(WORKFLOWS.values())


def get_workflow(name: str) -> Workflow:
    """Look up a workflow by name, accepting ``extract-tissue`` spelling.

    Raises
    ------
    KeyError
        If no workflow has that name; the message suggests the closest one.
    """
    import rocqipath.api  # noqa: F401

    key = name.replace("-", "_")
    if key not in WORKFLOWS:
        close = difflib.get_close_matches(key, list(WORKFLOWS), n=1)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        raise KeyError(f"Unknown workflow {name!r}.{hint}")
    return WORKFLOWS[key]


def run(name: str, inputs: Any, output_dir: Any, **params: Any) -> Result:
    """Run a workflow by name.

    Parameters
    ----------
    name : str
        Registered workflow name (``"align"``, ``"count-cells"``, ...).
    inputs, output_dir
        Passed to the workflow unchanged.
    **params
        ``config=`` and/or field overrides and workflow options.

    Returns
    -------
    Result
        The workflow's result.
    """
    return get_workflow(name).function(inputs, output_dir, **params)


__all__ = [
    "WORKFLOWS",
    "InputSpec",
    "Item",
    "Result",
    "Workflow",
    "get_workflow",
    "list_workflows",
    "run",
    "workflow",
]
