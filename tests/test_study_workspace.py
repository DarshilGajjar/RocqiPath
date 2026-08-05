"""Descriptor, index, pair derivation, and verification behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from rocqipath.core.exceptions import ConfigurationError
from rocqipath.study import (
    Study,
    StudyDescriptor,
    derive_pairs,
    descriptor_template,
    load_descriptor,
    load_index,
    make_slide_uid,
    verify_study,
)
from rocqipath.study.descriptor import DescriptorNotFoundError
from rocqipath.study.study import StudyNotFoundError


def _archive(root: Path, names) -> Path:
    """Create placeholder slide files and return their directory."""
    archive = root / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    for name in names:
        (archive / name).write_bytes(b"placeholder")
    return archive


def _study(tmp_path: Path, names, stains=("he", "cd8")) -> Study:
    """Create a study whose descriptor points at a placeholder archive."""
    archive = _archive(tmp_path, names)
    return Study.create(
        "cohort",
        sources=[archive],
        stains=stains,
        home=tmp_path / "home",
    )


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "source",
    [
        (
            r"\\dept01cap\oralonc$\48 Seshadri Lab Data Share"
            r"\Lab Members\Darshil Gajjar\1) Study\5) PyStain"
            r"\main\output\tma\block12"
        ),
        r"C:\Users\Darshil\Desktop\slides",
        "C:/Users/Darshil/Desktop/slides",
        "/mnt/archive/pathology/slides",
        r"\\server\share\O'Brien Study\slides",
        'C:\\Research\\"quoted study"\\slides',
        r"//server/share/pathology/slides",
        r"C:\Users\Darshil\Δ-study\slides",
    ],
)
def test_descriptor_template_round_trips_source_paths(
    tmp_path: Path,
    source: str,
) -> None:
    descriptor_path = tmp_path / "study.toml"

    descriptor_path.write_text(
        descriptor_template(
            "path_test",
            sources=[source],
            stains=["he", "cd8"],
        ),
        encoding="utf-8",
    )

    descriptor = load_descriptor(descriptor_path)

    assert len(descriptor.sources) == 1
    assert str(descriptor.sources[0].root) == source

def test_descriptor_template_round_trips_multiple_source_paths(
    tmp_path: Path,
) -> None:
    sources = [
        r"\\server\share\he slides",
        r"D:\Pathology\CD8 slides",
        "/mnt/archive/cd31",
    ]

    descriptor_path = tmp_path / "study.toml"

    descriptor_path.write_text(
        descriptor_template(
            "multi_source_test",
            sources=sources,
            stains=["he", "cd8"],
        ),
        encoding="utf-8",
    )

    descriptor = load_descriptor(descriptor_path)

    loaded = [str(source.root) for source in descriptor.sources]

    assert loaded == sources

def test_descriptor_rejects_control_characters_in_source_path() -> None:
    corrupted_path = "C:\\study\\1data"

    # Simulate a string containing an actual control character.
    corrupted_path = corrupted_path.replace("\\1", "\x01")

    with pytest.raises(ConfigurationError, match="control characters"):
        descriptor_template(
            "invalid_path",
            sources=[corrupted_path],
        )

def test_template_round_trips_through_the_parser(tmp_path: Path) -> None:
    path = tmp_path / "study.toml"
    path.write_text(descriptor_template("demo", sources=[tmp_path], stains=["he", "cd8"]))
    descriptor = load_descriptor(path)
    assert descriptor.name == "demo"
    assert descriptor.reference_stains == ["he"]
    assert descriptor.moving_stains == ["cd8"]
    assert descriptor.validate() == []


def test_missing_descriptor_is_a_file_not_found_error(tmp_path: Path) -> None:
    with pytest.raises(DescriptorNotFoundError):
        load_descriptor(tmp_path / "absent.toml")
    assert issubclass(DescriptorNotFoundError, FileNotFoundError)


def test_validate_reports_two_reference_stains() -> None:
    descriptor = StudyDescriptor.from_mapping(
        {
            "name": "x",
            "sources": [{"root": "/tmp"}],
            "stains": {"he": {"role": "reference"}, "pas": {"role": "reference"}},
        }
    )
    assert any("Multiple reference stains" in item for item in descriptor.validate())


def test_pattern_without_required_groups_is_rejected() -> None:
    descriptor = StudyDescriptor.from_mapping(
        {
            "name": "x",
            "sources": [{"root": "/tmp", "pattern": r"(?P<case>.+)\.svs"}],
            "stains": {"he": {"role": "reference"}},
        }
    )
    assert any("named group" in item for item in descriptor.validate())


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
def test_slide_uid_keeps_underscores_in_case_ids() -> None:
    assert make_slide_uid("BLOCK_12_A", "cd8", 3) == "BLOCK_12_A__cd8__s03"


def test_index_decodes_case_stain_and_section(tmp_path: Path) -> None:
    study = _study(tmp_path, ["CASE-1_he.svs", "CASE-1_cd8_s02.svs"])
    records = study.index()
    assert [item.slide_uid for item in records] == [
        "CASE-1__cd8__s02",
        "CASE-1__he__s01",
    ]
    assert {item.role for item in records} == {"reference", "moving"}


def test_index_round_trips_through_jsonl(tmp_path: Path) -> None:
    study = _study(tmp_path, ["CASE-1_he.svs", "CASE-1_cd8.svs"])
    written = study.index()
    assert load_index(study.paths.index) == written


def test_undeclared_stain_produces_a_warning(tmp_path: Path) -> None:
    study = _study(tmp_path, ["CASE-1_he.svs", "CASE-1_pdl1.svs"])
    study.index()
    assert any("pdl1" in warning for warning in study.index_warnings)


def test_one_reference_serves_every_biomarker_without_duplication(tmp_path: Path) -> None:
    study = _study(
        tmp_path,
        ["CASE-1_he.svs", "CASE-1_cd8.svs", "CASE-1_cd31.svs"],
        stains=("he", "cd8", "cd31"),
    )
    records = study.index()
    pairs = derive_pairs(records)
    assert len(pairs) == 2
    assert {pair.biomarker for pair in pairs} == {"cd8", "cd31"}
    # The same physical file backs both pairs; nothing was copied.
    assert len({pair.reference.path for pair in pairs}) == 1
    assert sum(1 for item in records if item.stain == "he") == 1


def test_excluded_slides_are_dropped_from_pairs(tmp_path: Path) -> None:
    study = _study(tmp_path, ["CASE-1_he.svs", "CASE-1_cd8.svs"])
    descriptor = study.paths.descriptor
    descriptor.write_text(
        descriptor.read_text()
        + '\n[overrides."CASE-1__cd8__s01"]\nexclude = true\nnote = "damaged"\n'
    )
    study.reload()
    assert derive_pairs(study.index()) == []


def test_override_supplies_missing_source_magnification(tmp_path: Path) -> None:
    study = _study(tmp_path, ["CASE-1_he.svs", "CASE-1_cd8.svs"])
    descriptor = study.paths.descriptor
    descriptor.write_text(
        descriptor.read_text() + '\n[overrides."CASE-1__he__s01"]\nsource_magnification = 80.0\n'
    )
    study.reload()
    record = {item.slide_uid: item for item in study.index()}["CASE-1__he__s01"]
    assert record.source_magnification == 80.0


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def test_verify_flags_a_case_with_no_reference_slide(tmp_path: Path) -> None:
    study = _study(tmp_path, ["CASE-1_he.svs", "CASE-1_cd8.svs", "CASE-2_cd8.svs"])
    study.index()
    report = study.verify()
    assert not report.ok
    assert any(item.scope == "CASE-2" for item in report.errors)


def test_verify_passes_on_a_complete_cohort(tmp_path: Path) -> None:
    study = _study(tmp_path, ["CASE-1_he.svs", "CASE-1_cd8.svs"])
    study.index()
    report = study.verify()
    assert report.ok, report.format()
    assert report.checked["cases"] == 1


def test_verify_reports_an_empty_index(tmp_path: Path) -> None:
    study = _study(tmp_path, [])
    study.index()
    report = verify_study(study.descriptor, [])
    assert not report.ok
    assert "No slides were indexed." in report.format()


# ---------------------------------------------------------------------------
# Study facade
# ---------------------------------------------------------------------------
def test_open_missing_study_is_a_file_not_found_error(tmp_path: Path) -> None:
    with pytest.raises(StudyNotFoundError):
        Study.open("absent", home=tmp_path)
    assert issubclass(StudyNotFoundError, FileNotFoundError)


def test_create_refuses_to_clobber_an_existing_descriptor(tmp_path: Path) -> None:
    Study.create("cohort", home=tmp_path)
    with pytest.raises(ConfigurationError):
        Study.create("cohort", home=tmp_path)
    assert Study.create("cohort", home=tmp_path, overwrite=True).name == "cohort"


def test_home_environment_variable_is_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROCQIPATH_HOME", str(tmp_path / "workspace"))
    study = Study.create("cohort")
    assert study.root == (tmp_path / "workspace" / "cohort").resolve()


def test_summary_reports_current_state(tmp_path: Path) -> None:
    study = _study(tmp_path, ["CASE-1_he.svs", "CASE-1_cd8.svs"])
    study.index()
    summary = study.summary()
    assert summary["slides"] == 2
    assert summary["cases"] == 1
    assert summary["has_recipe"] is False
