"""CLI tests: exit-code contract, output formats, determinism.

The command lives in a ``gate`` group (``specify gate check``) so that the root
command list asserted by the upstream suite stays intact.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from specify_cli import app
from specify_cli.gate.render import to_json
from specify_cli.gate.engine import evaluate

from .builders import CLEAN_TASKS, replace, write_set

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, ["gate", "check", *args])


def test_clean_project_exits_zero(tmp_path: Path) -> None:
    write_set(tmp_path)
    result = run(str(tmp_path))
    assert result.exit_code == 0, result.output
    assert "no findings" in result.output
    assert "coverage=100.0%" in result.output


def test_high_finding_exits_one(tmp_path: Path) -> None:
    write_set(tmp_path, tasks=replace(CLEAN_TASKS, " (FR-002)", ""))
    result = run(str(tmp_path))
    assert result.exit_code == 1
    assert "SG003" in result.output


def test_fail_on_medium_ignores_low(tmp_path: Path) -> None:
    write_set(tmp_path, tasks=replace(CLEAN_TASKS, " (FR-002)", ""))
    assert run(str(tmp_path), "--fail-on", "never").exit_code == 0
    assert run(str(tmp_path), "--fail-on", "low").exit_code == 1


def test_missing_path_exits_two(tmp_path: Path) -> None:
    result = run(str(tmp_path / "does-not-exist"))
    assert result.exit_code == 2


def test_without_feature_directory_exits_zero(tmp_path: Path) -> None:
    result = run(str(tmp_path))
    assert result.exit_code == 0


def test_json_is_multiple_documents_and_stable(tmp_path: Path) -> None:
    write_set(tmp_path)
    write_set(
        tmp_path,
        directory="specs/002-other",
        spec="# S\n\n## Requirements\n\n- **FR-001**: x\n",
        tasks="# Tasks\n\n- [ ] T001 do `a.py` (FR-001)\n",
        plan="# P\n",
    )
    first = run(str(tmp_path), "--format", "json")
    second = run(str(tmp_path), "--format", "json")
    assert first.exit_code == 0
    assert first.output == second.output
    docs = []
    decoder = json.JSONDecoder()
    i = 0
    text = first.output
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        obj, i = decoder.raw_decode(text, i)
        docs.append(obj)
    assert len(docs) == 2
    assert docs[0]["gate"] == "specgate"
    assert docs[0]["counts"]["critical"] == 0
    assert "gate_version" in docs[0]
    assert docs[0]["directory"].startswith("specs/")


def test_sarif_output_is_valid(tmp_path: Path) -> None:
    write_set(tmp_path, tasks=replace(CLEAN_TASKS, " (FR-002)", ""))
    result = run(str(tmp_path), "--format", "sarif")
    assert result.exit_code == 1
    doc = json.loads(result.output)
    assert doc["version"] == "2.1.0"
    run_info = doc["runs"][0]
    assert run_info["tool"]["driver"]["name"] == "specgate"
    assert run_info["results"][0]["ruleId"] == "SG003"
    assert run_info["results"][0]["level"] == "error"


def test_baseline_flow(tmp_path: Path) -> None:
    write_set(tmp_path, tasks=replace(CLEAN_TASKS, " (FR-002)", ""))
    store = tmp_path / "gate-baseline.json"
    first = run(str(tmp_path), "--baseline", str(store), "--update-baseline")
    assert first.exit_code == 0, first.output
    assert store.exists()

    second = run(str(tmp_path), "--baseline", str(store))
    assert second.exit_code == 0
    assert "0 new" in second.output

    tasks = replace(CLEAN_TASKS, "(FR-001)", "(FR-404)")
    (tmp_path / "specs/001-widget-sync/tasks.md").write_text(
        tasks, encoding="utf-8", newline="\n"
    )
    third = run(str(tmp_path), "--baseline", str(store))
    assert third.exit_code == 1
    assert "SG002" in third.output or "SG003" in third.output


def test_broken_baseline_exits_three(tmp_path: Path) -> None:
    write_set(tmp_path)
    store = tmp_path / "baseline.json"
    store.write_text("not json", encoding="utf-8")
    assert run(str(tmp_path), "--baseline", str(store)).exit_code == 3


def test_update_baseline_requires_path(tmp_path: Path) -> None:
    write_set(tmp_path)
    assert run(str(tmp_path), "--update-baseline").exit_code == 2


def test_bad_format_rejected(tmp_path: Path) -> None:
    write_set(tmp_path)
    assert run(str(tmp_path), "--format", "yaml").exit_code != 0


def test_quiet_prints_nothing_on_success(tmp_path: Path) -> None:
    write_set(tmp_path)
    result = run(str(tmp_path), "--quiet")
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_determinism_across_runs_and_cwd(tmp_path: Path, monkeypatch) -> None:
    feature = write_set(tmp_path, tasks=replace(CLEAN_TASKS, " (FR-002)", ""))
    first = to_json(evaluate(feature, tmp_path), strict=True)
    monkeypatch.chdir(tmp_path)
    second = to_json(evaluate(feature, tmp_path), strict=True)
    assert first == second
    assert str(tmp_path) not in first  # no absolute paths in machine output
    assert "\\" not in first.split('"files"')[0]
