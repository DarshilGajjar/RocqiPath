"""Recipe, manifest, selection, result-table, staging, and CLI behaviour."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rocqipath.study import (
    ManifestWriter,
    Study,
    aggregate,
    build_recipe,
    build_selection,
    compute_recipe_hash,
    evaluate_rule,
    load_recipe,
    load_selection,
    read_manifest,
    read_manifest_info,
)
from rocqipath.study.recipe import Recipe
from rocqipath.study.selection import RuleError, rule_from_thresholds
from rocqipath.study.stages import resolve_stage_order, run_stage
from rocqipath.study.staging import stage_pairs, stage_slides


def _study(tmp_path: Path, names=("CASE-1_he.svs", "CASE-1_cd8.svs")) -> Study:
    """Create a study over placeholder slide files."""
    archive = tmp_path / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    for name in names:
        (archive / name).write_bytes(b"placeholder")
    study = Study.create("cohort", sources=[archive], home=tmp_path / "home")
    study.index()
    return study


_PATCHES = [
    {"uid": "p1", "case": "C1", "stain": "cd8", "tissue_fraction": 0.90, "blur": 40.0},
    {"uid": "p2", "case": "C1", "stain": "cd8", "tissue_fraction": 0.55, "blur": 12.0},
    {"uid": "p3", "case": "C1", "stain": "cd8", "tissue_fraction": 0.10, "blur": 80.0},
    {"uid": "p4", "case": "C2", "stain": "cd31", "tissue_fraction": 0.70, "blur": 5.0},
]


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------
def test_recipe_resolves_every_stage(tmp_path: Path) -> None:
    study = _study(tmp_path)
    recipe = study.plan()
    assert set(recipe.stages) >= {"tissue", "alignment", "patches", "stain", "counts"}
    assert recipe.stage("patches")["patch_size"] == 512
    assert recipe.recipe_hash


def test_recipe_hash_ignores_bookkeeping_fields() -> None:
    first = {"study": "a", "stages": {"x": {"n": 1}}, "generated_at": "2020", "recipe_hash": "z"}
    second = {"study": "a", "stages": {"x": {"n": 1}}, "generated_at": "2026", "recipe_hash": "q"}
    assert compute_recipe_hash(first) == compute_recipe_hash(second)


def test_recipe_hash_changes_when_a_decision_changes() -> None:
    base = {"study": "a", "stages": {"patches": {"patch_size": 512}}}
    changed = {"study": "a", "stages": {"patches": {"patch_size": 256}}}
    assert compute_recipe_hash(base) != compute_recipe_hash(changed)


def test_recipe_round_trips_through_disk(tmp_path: Path) -> None:
    study = _study(tmp_path)
    written = study.plan()
    assert load_recipe(study.paths.recipe).to_dict() == written.to_dict()


def test_overrides_are_applied_and_rejected_when_unknown(tmp_path: Path) -> None:
    study = _study(tmp_path)
    recipe = study.plan(overrides={"patches": {"patch_size": 256}})
    assert recipe.stage("patches")["patch_size"] == 256
    with pytest.raises(Exception):
        build_recipe(study.descriptor, overrides={"nonexistent": {"a": 1}})


def test_extraction_defaults_measure_everything(tmp_path: Path) -> None:
    """Filtering belongs in a selection, so extraction thresholds start at zero."""
    recipe = _study(tmp_path).plan()
    assert recipe.stage("patches")["tissue_threshold"] == 0.0
    assert recipe.stage("counts")["tissue_threshold"] == 0.0


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------
def test_manifest_writes_rows_and_a_sidecar(tmp_path: Path) -> None:
    with ManifestWriter(tmp_path, "patches", stage="patches", study="s", recipe_hash="abc") as w:
        w.write_all(_PATCHES)
    rows = list(read_manifest(tmp_path / "patches.jsonl"))
    info = read_manifest_info(tmp_path / "patches.manifest.json")
    assert len(rows) == 4
    assert info.n_rows == 4
    assert info.recipe_hash == "abc"
    assert "tissue_fraction" in info.fields


def test_manifest_sidecar_is_written_even_after_an_exception(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        with ManifestWriter(tmp_path, "patches", stage="patches") as writer:
            writer.write(_PATCHES[0])
            raise RuntimeError("stage blew up")
    assert read_manifest_info(tmp_path / "patches.manifest.json").n_rows == 1


def test_manifest_append_continues_the_row_count(tmp_path: Path) -> None:
    with ManifestWriter(tmp_path, "patches", stage="patches") as writer:
        writer.write(_PATCHES[0])
    with ManifestWriter(tmp_path, "patches", stage="patches", append=True) as writer:
        writer.write(_PATCHES[1])
    assert read_manifest_info(tmp_path / "patches.manifest.json").n_rows == 2


# ---------------------------------------------------------------------------
# Selection rules
# ---------------------------------------------------------------------------
def test_empty_rule_selects_everything() -> None:
    assert len(evaluate_rule("", _PATCHES)) == 4


def test_threshold_rule_filters_rows() -> None:
    kept = evaluate_rule("tissue_fraction >= 0.6", _PATCHES)
    assert [row["uid"] for row in kept] == ["p1", "p4"]


def test_chained_comparison_and_boolean_logic() -> None:
    kept = evaluate_rule("0.5 <= tissue_fraction < 0.8 and blur > 10", _PATCHES)
    assert [row["uid"] for row in kept] == ["p2"]
    assert [row["uid"] for row in evaluate_rule("0.5 <= tissue_fraction < 0.8", _PATCHES)] == [
        "p2",
        "p4",
    ]


def test_membership_test_on_a_string_field() -> None:
    kept = evaluate_rule('stain in ["cd31"]', _PATCHES)
    assert [row["uid"] for row in kept] == ["p4"]


def test_percentile_helper_is_computed_over_the_manifest() -> None:
    kept = evaluate_rule("blur >= percentile('blur', 50)", _PATCHES)
    assert [row["uid"] for row in kept] == ["p1", "p3"]


def test_missing_fields_never_match_a_threshold() -> None:
    rows = [{"uid": "a", "tissue_fraction": 0.9}, {"uid": "b"}]
    assert [row["uid"] for row in evaluate_rule("tissue_fraction >= 0.5", rows)] == ["a"]


def test_rules_cannot_call_arbitrary_python() -> None:
    for rule in (
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "(lambda: 1)()",
        "[x for x in range(3)]",
    ):
        with pytest.raises(RuleError):
            evaluate_rule(rule, _PATCHES)


def test_rule_syntax_errors_are_reported_clearly() -> None:
    with pytest.raises(RuleError, match="Could not parse"):
        evaluate_rule("tissue_fraction >=", _PATCHES)


def test_rule_from_thresholds_composes_an_expression() -> None:
    assert rule_from_thresholds(tissue_fraction=0.6, blur=10) == (
        "blur >= 10 and tissue_fraction >= 0.6"
    )


# ---------------------------------------------------------------------------
# Selections on disk
# ---------------------------------------------------------------------------
def test_selection_records_provenance_and_round_trips(tmp_path: Path) -> None:
    selection = build_selection(
        "strict",
        _PATCHES,
        "tissue_fraction >= 0.6",
        study="cohort",
        stage="patches",
        recipe_hash="abc123",
        stat_fields=("tissue_fraction", "blur"),
    )
    assert selection.n_input == 4
    assert selection.n_selected == 2
    assert selection.uids == ["p1", "p4"]
    assert selection.fraction_kept == 0.5
    assert selection.stats["tissue_fraction"]["max"] == 0.9
    path = selection.write(tmp_path)
    assert load_selection(path).to_dict() == selection.to_dict()


def test_changing_a_threshold_does_not_touch_the_manifest(tmp_path: Path) -> None:
    """The point of selections: re-deciding is cheap and non-destructive."""
    study = _study(tmp_path)
    study.plan()
    patches_dir = study.paths.stage_dir("patches", create=True)
    with ManifestWriter(patches_dir, "patches", stage="patches") as writer:
        writer.write_all(_PATCHES)
    before = (patches_dir / "patches.jsonl").read_bytes()

    loose = study.select("loose", tissue_fraction=0.5)
    strict = study.select("strict", tissue_fraction=0.8)

    assert loose.n_selected == 3
    assert strict.n_selected == 1
    assert (patches_dir / "patches.jsonl").read_bytes() == before
    assert sorted(study.selections()) == ["loose", "strict"]


def test_selection_rule_and_thresholds_combine(tmp_path: Path) -> None:
    study = _study(tmp_path)
    study.plan()
    with ManifestWriter(
        study.paths.stage_dir("patches", create=True), "patches", stage="patches"
    ) as writer:
        writer.write_all(_PATCHES)
    selection = study.select("both", rule="blur >= 10", tissue_fraction=0.6)
    assert selection.uids == ["p1"]
    assert "and" in selection.rule


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
def test_aggregate_groups_and_counts() -> None:
    table = aggregate(_PATCHES, group_by=("case",), mean_fields=("tissue_fraction",))
    rows = {row["case"]: row for row in table}
    assert rows["C1"]["n"] == 3
    assert rows["C2"]["tissue_fraction_mean"] == pytest.approx(0.70)


def test_aggregate_honours_a_selection() -> None:
    selection = build_selection("s", _PATCHES, "tissue_fraction >= 0.6")
    table = aggregate(_PATCHES, group_by=("case",), selection=selection)
    assert {row["case"]: row["n"] for row in table} == {"C1": 1, "C2": 1}


def test_result_table_writes_csv(tmp_path: Path) -> None:
    table = aggregate(_PATCHES, group_by=("case",))
    path = table.to_csv(tmp_path / "results.csv")
    text = path.read_text().splitlines()
    assert text[0].startswith("case,n")
    assert len(text) == 3


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------
def test_staging_names_slides_by_uid(tmp_path: Path) -> None:
    study = _study(tmp_path)
    tree = stage_slides(study.slides(), tmp_path / "staged")
    assert sorted(tree.entries) == ["CASE-1__cd8__s01.svs", "CASE-1__he__s01.svs"]
    assert all(mode in ("symlink", "hardlink") for mode in tree.modes.values())


def test_pair_staging_reuses_one_reference_across_biomarkers(tmp_path: Path) -> None:
    study = _study(
        tmp_path,
        names=("CASE-1_he.svs", "CASE-1_cd8.svs", "CASE-1_cd31.svs"),
    )
    descriptor = study.paths.descriptor
    descriptor.write_text(descriptor.read_text() + '\n[stains.cd31]\nrole = "moving"\n')
    study.reload()
    study.index()
    tree = stage_pairs(study.pairs(), tmp_path / "pairs")
    references = [value for key, value in tree.entries.items() if "reference" in key]
    assert len(references) == 2
    assert len(set(references)) == 1  # same physical file, linked twice


# ---------------------------------------------------------------------------
# Stage orchestration
# ---------------------------------------------------------------------------
def test_stage_order_is_dependency_ordered() -> None:
    assert resolve_stage_order(["counts", "alignment"]) == ["alignment", "counts"]
    assert resolve_stage_order() == ["tissue", "alignment", "patches", "stain", "counts"]


def test_unknown_stage_is_rejected() -> None:
    with pytest.raises(Exception, match="Unknown stage"):
        resolve_stage_order(["nonsense"])


def test_dry_run_resolves_inputs_without_executing(tmp_path: Path) -> None:
    study = _study(tmp_path)
    results = {item.stage: item for item in study.run(dry_run=True, stop_on_error=False)}
    assert results["alignment"].status == "planned"
    assert results["alignment"].n_items == 1
    assert results["alignment"].detail["pairs"] == ["CASE-1__he-cd8"]
    assert not (study.paths.staging / "alignment").exists()


def test_disabled_stage_is_skipped(tmp_path: Path) -> None:
    study = _study(tmp_path)
    recipe = study.plan(overrides={"tissue": {"enabled": False}})
    result = run_stage("tissue", study.paths, recipe, study.slides(), dry_run=True)
    assert result.status == "skipped"


def test_patches_without_alignment_fails_with_an_actionable_message(tmp_path: Path) -> None:
    study = _study(tmp_path)
    recipe = study.plan()
    result = run_stage("patches", study.paths, recipe, study.slides())
    assert result.status == "failed"
    assert "alignment" in (result.error or "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli(argv, home: Path) -> int:
    """Invoke the console entry point with a workspace override."""
    from rocqipath.cli import main

    return main([*argv, "--home", str(home)] if "--home" not in argv else argv)


def test_cli_init_index_verify_plan(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from rocqipath.cli import main

    home = tmp_path / "home"
    archive = tmp_path / "archive"
    archive.mkdir()
    for name in ("CASE-1_he.svs", "CASE-1_cd8.svs"):
        (archive / name).write_bytes(b"placeholder")

    assert main(["study", "--home", str(home), "init", "cohort", "--source", str(archive)]) == 0
    assert main(["study", "--home", str(home), "index", "cohort"]) == 0
    assert main(["study", "--home", str(home), "verify", "cohort"]) == 0
    assert main(["study", "--home", str(home), "plan", "cohort"]) == 0
    assert main(["study", "--home", str(home), "show", "cohort"]) == 0
    assert main(["study", "--home", str(home), "list"]) == 0
    assert (home / "cohort" / "recipe.json").is_file()
    assert "Indexed 2 slide(s)" in capsys.readouterr().out


def test_cli_verify_json_reports_failure(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from rocqipath.cli import main

    home = tmp_path / "home"
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "CASE-2_cd8.svs").write_bytes(b"placeholder")

    main(["study", "--home", str(home), "init", "cohort", "--source", str(archive)])
    main(["study", "--home", str(home), "index", "cohort"])
    capsys.readouterr()
    assert main(["study", "--home", str(home), "verify", "cohort", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


def test_cli_plan_accepts_setting_overrides(tmp_path: Path) -> None:
    from rocqipath.cli import main

    home = tmp_path / "home"
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "CASE-1_he.svs").write_bytes(b"placeholder")
    main(["study", "--home", str(home), "init", "cohort", "--source", str(archive)])
    main(["study", "--home", str(home), "index", "cohort"])
    assert (
        main(
            [
                "study",
                "--home",
                str(home),
                "plan",
                "cohort",
                "--set",
                "patches.patch_size=256",
            ]
        )
        == 0
    )
    recipe = Recipe.from_dict(json.loads((home / "cohort" / "recipe.json").read_text()))
    assert recipe.stage("patches")["patch_size"] == 256


def test_cli_doctor_runs_and_reports(capsys: pytest.CaptureFixture) -> None:
    from rocqipath.cli import main

    main(["doctor"])
    assert "RocqiPath environment report" in capsys.readouterr().out


def test_doctor_json_is_machine_readable(capsys: pytest.CaptureFixture) -> None:
    from rocqipath.cli import main

    main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "python_version" in payload
    assert "packages" in payload
