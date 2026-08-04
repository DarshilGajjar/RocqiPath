"""Present indexed slides to the existing directory-based pipelines.

RocqiPath's original pipelines take an input directory and glob it.  The study
index, by contrast, references slides wherever they happen to live, across any
number of source roots, under whatever names the scanner produced.

Staging bridges the two.  For each stage it builds a small tree of links named
by ``slide_uid`` and points the existing pipeline at that tree.  Nothing is
copied when the filesystem allows a link, so a 300-slide cohort stages in
under a second and costs no disk.

Link strategy, in order of preference:

``symlink``
    Default everywhere.  On Windows this needs Developer Mode or an elevated
    shell; RocqiPath falls back automatically when it is unavailable.
``hardlink``
    Used when symlinks are refused and the target sits on the same volume.
``copy``
    Last resort, and never silent — the caller is warned, because copying
    whole-slide images is expensive.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.study.index import SlideRecord

__all__ = ["LINK_MODES", "StagedTree", "stage_pairs", "stage_slides"]

LINK_MODES = ("auto", "symlink", "hardlink", "copy")


@dataclass
class StagedTree:
    """A staged input directory and how each entry was materialised.

    Attributes
    ----------
    root : pathlib.Path
        Directory handed to the underlying pipeline.
    entries : dict
        Staged filename mapped to its original slide path.
    modes : dict
        Staged filename mapped to ``symlink``, ``hardlink``, or ``copy``.
    warnings : list of str
        Anything the caller should know, notably any file that was copied.
    """

    root: Path
    entries: Dict[str, str] = field(default_factory=dict)
    modes: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def copied(self) -> List[str]:
        """Return staged names that required a full copy."""
        return sorted(name for name, mode in self.modes.items() if mode == "copy")


def _link_one(source: Path, target: Path, mode: str) -> str:
    """Materialise ``target`` from ``source`` and return the mode used.

    Parameters
    ----------
    source : pathlib.Path
        Original slide.
    target : pathlib.Path
        Staged path to create.
    mode : str
        One of :data:`LINK_MODES`.

    Returns
    -------
    str
        The mode actually used.

    Raises
    ------
    ConfigurationError
        If ``mode`` is not recognised, or an explicit mode fails.
    """
    if mode not in LINK_MODES:
        raise ConfigurationError(f"Unknown link mode {mode!r}. Use one of: {', '.join(LINK_MODES)}")
    if target.exists() or target.is_symlink():
        return "existing"

    order: Sequence[str] = ("symlink", "hardlink", "copy") if mode == "auto" else (mode,)
    last_error: Optional[Exception] = None
    for attempt in order:
        try:
            if attempt == "symlink":
                os.symlink(source, target)
            elif attempt == "hardlink":
                os.link(source, target)
            else:
                shutil.copy2(source, target)
            return attempt
        except (OSError, NotImplementedError) as exc:
            last_error = exc
            continue
    raise ConfigurationError(f"Could not stage {source} as {target}: {last_error}")


def _stage_file(record: SlideRecord, directory: Path, name: str, mode: str) -> tuple[str, str]:
    """Stage one slide into ``directory`` under ``name``."""
    source = record.file
    if not source.is_file():
        raise ConfigurationError(f"Slide is missing: {source}")
    target = directory / name
    used = _link_one(source, target, mode)
    return name, used


def stage_slides(
    records: Iterable[SlideRecord],
    directory: Path,
    *,
    link_mode: str = "auto",
    clear: bool = True,
) -> StagedTree:
    """Stage a flat directory of slides named by ``slide_uid``.

    Parameters
    ----------
    records : iterable of SlideRecord
        Slides to stage.
    directory : pathlib.Path
        Staging directory, created if missing.
    link_mode : str, default "auto"
        One of :data:`LINK_MODES`.
    clear : bool, default True
        Remove any previous staging tree first.

    Returns
    -------
    StagedTree
        The staged directory and per-entry details.
    """
    root = Path(directory)
    if clear and root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    tree = StagedTree(root=root)
    for record in records:
        if record.excluded:
            continue
        name = f"{record.slide_uid}{record.file.suffix}"
        staged, mode = _stage_file(record, root, name, link_mode)
        tree.entries[staged] = record.path
        tree.modes[staged] = mode
    if tree.copied:
        tree.warnings.append(
            f"{len(tree.copied)} slide(s) had to be copied because neither symlinks "
            "nor hardlinks were available. On Windows, enabling Developer Mode lets "
            "RocqiPath use symlinks instead."
        )
    return tree


def stage_pairs(
    pairs: Sequence["object"],
    directory: Path,
    *,
    link_mode: str = "auto",
    reference_name: str = "reference",
    moving_name: str = "moving",
    clear: bool = True,
) -> StagedTree:
    """Stage the ``<biomarker>/<role>/`` tree the alignment pipeline expects.

    Because pairs are derived rather than stored, one reference slide is
    linked into every biomarker folder that needs it — at zero disk cost,
    which is the whole point of not duplicating whole-slide images.

    Parameters
    ----------
    pairs : sequence of SlidePair
        Pairs to stage.
    directory : pathlib.Path
        Staging root.
    link_mode : str, default "auto"
        One of :data:`LINK_MODES`.
    reference_name, moving_name : str
        Role tokens used in the staged filenames.
    clear : bool, default True
        Remove any previous staging tree first.

    Returns
    -------
    StagedTree
        The staged directory and per-entry details.
    """
    root = Path(directory)
    if clear and root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    tree = StagedTree(root=root)
    for pair in pairs:
        biomarker_dir = root / getattr(pair, "biomarker")
        reference_dir = biomarker_dir / reference_name
        moving_dir = biomarker_dir / moving_name
        reference_dir.mkdir(parents=True, exist_ok=True)
        moving_dir.mkdir(parents=True, exist_ok=True)

        reference = getattr(pair, "reference")
        moving = getattr(pair, "moving")
        case = getattr(pair, "case")

        for record, folder, role in (
            (reference, reference_dir, reference_name),
            (moving, moving_dir, moving_name),
        ):
            name = f"{case}_{role}{record.file.suffix}"
            staged, mode = _stage_file(record, folder, name, link_mode)
            key = str((folder / staged).relative_to(root))
            tree.entries[key] = record.path
            tree.modes[key] = mode

    if tree.copied:
        tree.warnings.append(
            f"{len(tree.copied)} slide(s) had to be copied into the staging tree. "
            "Enable symlinks (Developer Mode on Windows) to avoid duplicating "
            "whole-slide images."
        )
    return tree
