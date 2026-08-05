"""Read, validate, and generate the ``study.toml`` cohort descriptor.

The descriptor is the one file a user writes by hand.  It records the facts
that apply to a whole cohort — where the slides are, how their filenames encode
identity, which stain plays which role — so that no pipeline ever has to ask
for a directory again.

RocqiPath uses TOML for hand-authored files and JSON for generated ones.  The
distinction is deliberate: you can tell at a glance whether a file is yours to
edit, and TOML permits the comments that explain why an override exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.core.magnification import DEFAULT_TARGET_MAGNIFICATION

__all__ = [
    "DEFAULT_SLIDE_PATTERN",
    "REFERENCE_ROLE",
    "MOVING_ROLE",
    "SlideOverride",
    "SourceSpec",
    "StainSpec",
    "StudyDescriptor",
    "DescriptorNotFoundError",
    "descriptor_template",
    "load_descriptor",
]

REFERENCE_ROLE = "reference"
MOVING_ROLE = "moving"
_VALID_ROLES = (REFERENCE_ROLE, MOVING_ROLE)

#: Matches ``<case>_<stain>[_s<NN>].<ext>``; the section group is optional.
DEFAULT_SLIDE_PATTERN = (
    r"(?P<case>.+?)_(?P<stain>[A-Za-z0-9&+-]+?)"
    r"(?:_s(?P<section>\d+))?\.(?:svs|ndpi|tif|tiff|scn|mrxs|vsi|czi)$"
)

_SLIDE_SUFFIXES = (
    ".svs",
    ".ndpi",
    ".tif",
    ".tiff",
    ".scn",
    ".mrxs",
    ".vsi",
    ".czi",
    ".bif",
    ".svslide",
)


class DescriptorNotFoundError(ConfigurationError, FileNotFoundError):
    """Raised when a study directory has no ``study.toml``.

    Inherits :class:`FileNotFoundError` so callers that already handle a
    missing input file keep working unchanged.
    """

def _toml_basic_string(value: object) -> str:
    """Return ``value`` encoded as a valid TOML basic string.

    This safely handles:

    - Windows UNC paths
    - Windows drive-letter paths
    - POSIX paths
    - forward-slash network paths
    - spaces
    - apostrophes
    - double quotes
    - Unicode characters
    - tabs, newlines, and other control characters
    """
    text = str(value)

    escapes = {
        '"': r"\"",
        "\\": r"\\",
        "\b": r"\b",
        "\t": r"\t",
        "\n": r"\n",
        "\f": r"\f",
        "\r": r"\r",
    }

    encoded: List[str] = []

    for character in text:
        if character in escapes:
            encoded.append(escapes[character])
        elif ord(character) < 0x20 or ord(character) == 0x7F:
            encoded.append(f"\\u{ord(character):04X}")
        else:
            encoded.append(character)

    return '"' + "".join(encoded) + '"'

def _source_path_text(value: Union[str, Path]) -> str:
    """Normalize a source path and reject Python-escaped control characters."""
    text = str(Path(value).expanduser())

    control_characters = [
        character
        for character in text
        if ord(character) < 0x20 or ord(character) == 0x7F
    ]

    if control_characters:
        escaped = repr(text)

        raise ConfigurationError(
            "The source path contains control characters and was probably "
            "created from a non-raw Windows string. "
            f"Received: {escaped}. "
            "Use a raw string such as "
            r'r"\\server\share\folder" or pass pathlib.Path.'
        )

    return text

def _load_toml(path: Path) -> Dict[str, Any]:
    """Parse a TOML file using ``tomllib`` or the ``tomli`` backport.

    Parameters
    ----------
    path : pathlib.Path
        File to read.

    Returns
    -------
    dict
        Parsed document.

    Raises
    ------
    ConfigurationError
        If no TOML parser is importable or the document is malformed.
    """
    try:
        import tomllib as toml_reader
    except ModuleNotFoundError:  # Python 3.10
        try:
            import tomli as toml_reader  # type: ignore[no-redef]
        except ModuleNotFoundError as exc:  # pragma: no cover - packaging guard
            raise ConfigurationError(
                "Reading study.toml on Python 3.10 requires the 'tomli' backport. "
                "Install it with: python -m pip install tomli"
            ) from exc
    try:
        with open(path, "rb") as stream:
            return toml_reader.load(stream)
    except Exception as exc:  # noqa: BLE001 - surfaced with file context
        raise ConfigurationError(f"Could not parse {path}: {exc}") from exc


@dataclass(frozen=True)
class SourceSpec:
    """One searchable slide location and the regex that decodes its filenames.

    Attributes
    ----------
    root : pathlib.Path
        Directory searched for slides.  Never written to.
    pattern : str
        Regex with at least ``case`` and ``stain`` named groups, and an
        optional ``section`` group.
    recursive : bool
        Whether sub-directories are searched.
    """

    root: Path
    pattern: str = DEFAULT_SLIDE_PATTERN
    recursive: bool = True

    @property
    def compiled(self) -> "re.Pattern[str]":
        """Return the compiled filename pattern.

        Returns
        -------
        re.Pattern
            Case-insensitive compiled regex.

        Raises
        ------
        ConfigurationError
            If the pattern is invalid or omits a required group.
        """
        try:
            compiled = re.compile(self.pattern, flags=re.IGNORECASE)
        except re.error as exc:
            raise ConfigurationError(f"Invalid source pattern {self.pattern!r}: {exc}") from exc
        missing = {"case", "stain"} - set(compiled.groupindex)
        if missing:
            names = ", ".join(sorted(missing))
            raise ConfigurationError(
                f"Source pattern must define named group(s): {names}. "
                f"Got groups: {sorted(compiled.groupindex) or 'none'}."
            )
        return compiled


@dataclass(frozen=True)
class StainSpec:
    """Cohort-level facts about one stain or biomarker.

    Attributes
    ----------
    name : str
        Lowercase stain key, matching the ``stain`` capture group.
    role : {"reference", "moving"}
        ``reference`` stains are registration targets (usually H&E);
        ``moving`` stains are warped onto them.
    chromogen : str, optional
        Chromogen used, for example ``"dab"``.  Drives counting defaults.
    display_name : str, optional
        Label used in figures and result tables.
    source_magnification : float, optional
        Fallback objective magnification for every slide of this stain when
        the scanner wrote no metadata.
    """

    name: str
    role: str = MOVING_ROLE
    chromogen: Optional[str] = None
    display_name: Optional[str] = None
    source_magnification: Optional[float] = None

    def __post_init__(self) -> None:
        """Validate the declared role.

        Raises
        ------
        ConfigurationError
            If ``role`` is not a recognised value.
        """
        if self.role not in _VALID_ROLES:
            valid = ", ".join(_VALID_ROLES)
            raise ConfigurationError(
                f"Stain {self.name!r} has role {self.role!r}; expected one of: {valid}."
            )

    @property
    def label(self) -> str:
        """Return the display name, falling back to the uppercased key."""
        return self.display_name or self.name.upper()


@dataclass(frozen=True)
class SlideOverride:
    """Per-slide corrections that cannot be expressed cohort-wide.

    Attributes
    ----------
    source_magnification : float, optional
        Level-0 objective magnification for a slide whose scanner wrote none.
    exclude : bool
        Drop this slide from the study entirely.
    note : str, optional
        Free text explaining why the override exists.
    """

    source_magnification: Optional[float] = None
    exclude: bool = False
    note: Optional[str] = None


@dataclass
class StudyDescriptor:
    """Parsed ``study.toml``: everything the user declares about a cohort.

    Attributes
    ----------
    name : str
        Study name.
    sources : list of SourceSpec
        Slide locations searched during indexing.
    stains : dict of str to StainSpec
        Declared stains, keyed by lowercase stain name.
    overrides : dict of str to SlideOverride
        Per-slide corrections, keyed by ``slide_uid``.
    default_magnification : float
        Physical output magnification used unless a stage overrides it.
    detection_magnification : float
        Low-magnification zoom used for tissue and core detection.
    patch_size, stride : int
        Paired-patch grid defaults.
    alignment_method : {"valis", "orb"}
        Registration backend default.
    normalizer : str
        Stain-normalisation method default.
    description : str, optional
        Free text carried into generated reports.
    """

    name: str
    sources: List[SourceSpec] = field(default_factory=list)
    stains: Dict[str, StainSpec] = field(default_factory=dict)
    overrides: Dict[str, SlideOverride] = field(default_factory=dict)
    default_magnification: float = DEFAULT_TARGET_MAGNIFICATION
    detection_magnification: float = 1.25
    patch_size: int = 512
    stride: Optional[int] = None
    alignment_method: str = "valis"
    normalizer: str = "macenko"
    description: Optional[str] = None

    # -- derived views ----------------------------------------------------
    @property
    def reference_stains(self) -> List[str]:
        """Return declared stain keys whose role is ``reference``."""
        return [key for key, spec in self.stains.items() if spec.role == REFERENCE_ROLE]

    @property
    def moving_stains(self) -> List[str]:
        """Return declared stain keys whose role is ``moving``."""
        return [key for key, spec in self.stains.items() if spec.role == MOVING_ROLE]

    def stain(self, name: str) -> Optional[StainSpec]:
        """Return the spec for ``name`` if declared, otherwise ``None``."""
        return self.stains.get(name.strip().lower())

    def override(self, slide_uid: str) -> SlideOverride:
        """Return the override for ``slide_uid``, or an empty override."""
        return self.overrides.get(slide_uid, SlideOverride())

    def validate(self) -> List[str]:
        """Return human-readable problems with this descriptor.

        Returns
        -------
        list of str
            Empty when the descriptor is usable as written.
        """
        problems: List[str] = []
        if not self.sources:
            problems.append("No [[sources]] declared; RocqiPath has nowhere to look for slides.")
        for source in self.sources:
            if not source.root.is_dir():
                problems.append(f"Source root does not exist: {source.root}")
            try:
                source.compiled
            except ConfigurationError as exc:
                problems.append(str(exc))
        if not self.stains:
            problems.append("No [stains.*] declared; stain roles cannot be resolved.")
        if len(self.reference_stains) > 1:
            joined = ", ".join(sorted(self.reference_stains))
            problems.append(
                f"Multiple reference stains declared ({joined}). Exactly one stain "
                'should carry role = "reference".'
            )
        if self.stains and not self.reference_stains:
            problems.append('No stain declares role = "reference"; pairs cannot be derived.')
        if self.default_magnification <= 0:
            problems.append("default_magnification must be greater than zero.")
        if self.detection_magnification <= 0:
            problems.append("detection_magnification must be greater than zero.")
        if self.detection_magnification > self.default_magnification:
            problems.append(
                "detection_magnification should be lower than default_magnification; "
                "detection runs on a coarse overview of the slide."
            )
        if self.patch_size <= 0:
            problems.append("patch_size must be a positive integer.")
        if self.stride is not None and self.stride <= 0:
            problems.append("stride must be a positive integer when set.")
        if self.alignment_method not in ("valis", "orb"):
            problems.append(
                f'alignment_method must be "valis" or "orb"; got {self.alignment_method!r}.'
            )
        return problems

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the descriptor for embedding in generated artifacts."""
        return {
            "name": self.name,
            "description": self.description,
            "default_magnification": self.default_magnification,
            "detection_magnification": self.detection_magnification,
            "patch_size": self.patch_size,
            "stride": self.stride,
            "alignment_method": self.alignment_method,
            "normalizer": self.normalizer,
            "sources": [
                {
                    "root": str(source.root),
                    "pattern": source.pattern,
                    "recursive": source.recursive,
                }
                for source in self.sources
            ],
            "stains": {
                key: {
                    "role": spec.role,
                    "chromogen": spec.chromogen,
                    "display_name": spec.display_name,
                    "source_magnification": spec.source_magnification,
                }
                for key, spec in self.stains.items()
            },
            "overrides": {
                key: {
                    "source_magnification": value.source_magnification,
                    "exclude": value.exclude,
                    "note": value.note,
                }
                for key, value in self.overrides.items()
            },
        }

    @classmethod
    def from_mapping(
        cls, data: Mapping[str, Any], *, name: Optional[str] = None
    ) -> "StudyDescriptor":
        """Build a descriptor from a parsed TOML mapping.

        Parameters
        ----------
        data : Mapping
            Parsed ``study.toml`` document.
        name : str, optional
            Fallback study name when the document omits one.

        Returns
        -------
        StudyDescriptor
            Parsed descriptor.  Call :meth:`validate` before use.

        Raises
        ------
        ConfigurationError
            If required keys are missing or malformed.
        """
        study_name = str(data.get("name") or name or "").strip()
        if not study_name:
            raise ConfigurationError("study.toml must declare a 'name'.")

        sources: List[SourceSpec] = []
        raw_sources = data.get("sources") or []
        if isinstance(raw_sources, Mapping):
            raw_sources = [raw_sources]
        for entry in raw_sources:
            if not isinstance(entry, Mapping) or "root" not in entry:
                raise ConfigurationError("Every [[sources]] entry must declare a 'root'.")
            sources.append(
                SourceSpec(
                    root=Path(str(entry["root"])).expanduser(),
                    pattern=str(entry.get("pattern", DEFAULT_SLIDE_PATTERN)),
                    recursive=bool(entry.get("recursive", True)),
                )
            )

        stains: Dict[str, StainSpec] = {}
        for key, value in (data.get("stains") or {}).items():
            if not isinstance(value, Mapping):
                raise ConfigurationError(f"[stains.{key}] must be a table of settings.")
            lowered = str(key).strip().lower()
            stains[lowered] = StainSpec(
                name=lowered,
                role=str(value.get("role", MOVING_ROLE)).strip().lower(),
                chromogen=_optional_str(value.get("chromogen")),
                display_name=_optional_str(value.get("display_name")),
                source_magnification=_optional_float(value.get("source_magnification")),
            )

        overrides: Dict[str, SlideOverride] = {}
        for key, value in (data.get("overrides") or {}).items():
            if not isinstance(value, Mapping):
                raise ConfigurationError(f'[overrides."{key}"] must be a table of settings.')
            overrides[str(key)] = SlideOverride(
                source_magnification=_optional_float(value.get("source_magnification")),
                exclude=bool(value.get("exclude", False)),
                note=_optional_str(value.get("note")),
            )

        return cls(
            name=study_name,
            sources=sources,
            stains=stains,
            overrides=overrides,
            default_magnification=float(
                data.get("default_magnification", DEFAULT_TARGET_MAGNIFICATION)
            ),
            detection_magnification=float(data.get("detection_magnification", 1.25)),
            patch_size=int(data.get("patch_size", 512)),
            stride=_optional_int(data.get("stride")),
            alignment_method=str(data.get("alignment_method", "valis")).strip().lower(),
            normalizer=str(data.get("normalizer", "macenko")).strip().lower(),
            description=_optional_str(data.get("description")),
        )


def _optional_str(value: Any) -> Optional[str]:
    """Return a stripped string, or ``None`` for empty and missing values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> Optional[float]:
    """Return ``value`` as a float, or ``None`` when unset."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Expected a number, got {value!r}.") from exc


def _optional_int(value: Any) -> Optional[int]:
    """Return ``value`` as an int, or ``None`` when unset."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Expected an integer, got {value!r}.") from exc


def load_descriptor(path: Union[str, Path], *, name: Optional[str] = None) -> StudyDescriptor:
    """Load and parse a ``study.toml`` file.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the descriptor.
    name : str, optional
        Fallback study name when the file omits one.

    Returns
    -------
    StudyDescriptor
        Parsed descriptor.

    Raises
    ------
    DescriptorNotFoundError
        If the file does not exist.
    """
    descriptor_path = Path(path)
    if not descriptor_path.is_file():
        raise DescriptorNotFoundError(
            f"No study descriptor at {descriptor_path}. "
            "Create one with: rocqipath study init <name> --source <slide-dir>"
        )
    return StudyDescriptor.from_mapping(_load_toml(descriptor_path), name=name)


def descriptor_template(
    name: str,
    sources: Sequence[Union[str, Path]] = (),
    stains: Sequence[str] = ("he", "cd8"),
    *,
    default_magnification: float = DEFAULT_TARGET_MAGNIFICATION,
) -> str:
    """Render a commented ``study.toml`` starting point.

    Parameters
    ----------
    name : str
        Study name written into the template.
    sources : sequence of str or pathlib.Path
        Slide directories.  A placeholder is written when empty.
    stains : sequence of str
        Stain keys.  The first is given the ``reference`` role.
    default_magnification : float
        Physical output magnification.

    Returns
    -------
    str
        TOML document ready to write to disk.
    """
    keys = [str(stain).strip().lower() for stain in stains if str(stain).strip()] or ["he"]
    roots = [_source_path_text(item) for item in sources] or ["/path/to/slide/archive"]

    lines: List[str] = [
        "# RocqiPath study descriptor.",
        "# This is the only file you write by hand. Everything else under this",
        "# directory is generated and safe to delete and rebuild.",
        "",
        f"name = {_toml_basic_string(name)}",
        f"default_magnification = {float(default_magnification):.1f}"
        "   # physical objective, not a pyramid level",
        "detection_magnification = 1.25",
        "patch_size = 512",
        'alignment_method = "valis"          # or "orb"',
        'normalizer = "macenko"              # reinhard | macenko | vahadane',
        "",
        "# --------------------------------------------------------------------",
        "# Where the slides live. Roots are read-only: RocqiPath references",
        "# slides in place and never copies or renames them.",
        "#",
        "# The pattern must capture 'case' and 'stain'. An optional 'section'",
        "# group distinguishes serial sections of the same block.",
        "# --------------------------------------------------------------------",
    ]
    for root in roots:
        lines += [
            "",
            "[[sources]]",
            f"root = {_toml_basic_string(root)}",
            f"pattern = '{DEFAULT_SLIDE_PATTERN}'",
            "recursive = true",
        ]

    lines += [
        "",
        "# --------------------------------------------------------------------",
        '# Stain roles. Exactly one stain carries role = "reference"; it is the',
        "# registration target every moving stain is warped onto.",
        "# --------------------------------------------------------------------",
    ]
    for position, key in enumerate(keys):
        role = REFERENCE_ROLE if position == 0 else MOVING_ROLE
        lines += ["", f"[stains.{key}]", f'role = "{role}"']
        if role == MOVING_ROLE:
            lines.append('chromogen = "dab"')

    lines += [
        "",
        "# --------------------------------------------------------------------",
        "# Per-slide corrections, keyed by slide_uid (<case>__<stain>__s<NN>).",
        "# Use these for slides whose scanner wrote no objective metadata, or",
        "# for slides that should be dropped from the cohort.",
        "# --------------------------------------------------------------------",
        "",
        '# [overrides."TMA12-A3__he__s01"]',
        "# source_magnification = 80.0",
        '# note = "Scanner wrote no objective-power tag."',
        "",
        '# [overrides."TMA12-B7__cd8__s01"]',
        "# exclude = true",
        '# note = "Coverslip damage across the core."',
        "",
    ]
    return "\n".join(lines)


def looks_like_slide(path: Path) -> bool:
    """Return whether ``path`` has a recognised whole-slide file extension."""
    return path.suffix.lower() in _SLIDE_SUFFIXES
