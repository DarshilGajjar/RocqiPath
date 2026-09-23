"""Turn whatever a user passes as ``inputs`` into a list of items.

Every workflow receives its inputs as :class:`~rocqipath.Item` objects:

* a file or folder path becomes one item with role ``"input"``;
* a :class:`~rocqipath.Result` contributes its items;
* a folder holding a ``rocqipath.json`` run manifest contributes the items
  recorded there.

When a workflow declares the roles it accepts (``InputSpec.roles``), items
from results and manifests are filtered to those roles, so passing the
output of ``rp.align`` to ``rp.count_cells`` counts the aligned slides and
ignores the QC figures. This is what lets workflows chain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Sequence

from rocqipath.io.manifest import RUN_MANIFEST, read_run_manifest

#: Role given to plain paths passed by the user.
INPUT_ROLE = "input"


def _items_from(value: Any) -> tuple[List[Any], str | None]:
    """Items for one input element, and a description when they come from a run."""
    from rocqipath.registry import Item, Result

    if isinstance(value, Result):
        return list(value.items), f"the {value.workflow} result"
    if isinstance(value, Item):
        return [value], f"the {value.role} item"
    path = Path(value).expanduser()
    if path.is_dir() and (path / RUN_MANIFEST).is_file():
        results = read_run_manifest(path)
        names = " and ".join(result.workflow for result in results) or "an empty"
        return [item for result in results for item in result.items], f"the {names} output"
    return [Item(sample_id=path.stem, role=INPUT_ROLE, path=path.resolve())], None


def resolve_inputs(inputs: Any, roles: Sequence[str] = ()) -> List[Any]:
    """Resolve a workflow's ``inputs`` argument into items.

    Parameters
    ----------
    inputs : path, Result, Item, or a list of them
        What the user passed.
    roles : sequence of str
        Roles the workflow accepts from recorded runs. Empty accepts all.

    Returns
    -------
    list of Item
        Items in the order given. Plain paths keep role ``"input"``.

    Raises
    ------
    FileNotFoundError
        If a path does not exist.
    ValueError
        If a recorded run holds none of the accepted roles.
    """
    from rocqipath.registry import Item, Result

    elements: Iterable[Any] = (
        [inputs] if isinstance(inputs, (str, Path, Result, Item)) else list(inputs)
    )
    resolved: List[Any] = []
    for element in elements:
        items, recorded = _items_from(element)
        if recorded and roles:
            accepted = [item for item in items if item.role in roles]
            if not accepted:
                found = sorted({item.role for item in items}) or ["nothing"]
                raise ValueError(
                    f"{recorded} holds {', '.join(found)} files; this workflow needs "
                    f"one of: {', '.join(roles)}"
                )
            items = accepted
        missing = [str(item.path) for item in items if not Path(item.path).exists()]
        if missing:
            raise FileNotFoundError(f"input not found: {', '.join(missing)}")
        resolved.extend(items)
    return resolved


__all__ = ["INPUT_ROLE", "resolve_inputs"]
