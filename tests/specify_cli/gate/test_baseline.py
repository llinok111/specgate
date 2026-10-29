"""Baseline tests: the snapshot must survive line shifts and report drift."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from specify_cli.gate import baseline
from specify_cli.gate.engine import evaluate
from specify_cli.gate.model import Finding

from .builders import CLEAN_TASKS, replace, write_set


def make(
    rule: str = "SG003", artifact: str = "specs/001/spec.md", msg: str = "x"
) -> Finding:
    return Finding(
        rule=rule,
        severity="high",
        tier="core",
        artifact=artifact,
        line=1,
        message=msg,
        subject="FR-001",
    )


def test_fingerprint_ignores_line_number() -> None:
    a = Finding("SG003", "high", "core", "spec.md", 10, "FR-001 uncovered", "FR-001")
    b = Finding("SG003", "high", "core", "spec.md", 42, "FR-001 uncovered", "FR-001")
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_changes_with_message() -> None:
    assert make(msg="a").fingerprint() != make(msg="b").fingerprint()


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "gate-baseline.json"
    baseline.write(path, [make(), make(rule="SG004", msg="dup")])
    accepted = baseline.read(path)
    assert len(accepted) == 2
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["gate"] == "specgate"
    assert raw["fingerprints"] == sorted(raw["fingerprints"])
    assert path.read_bytes().endswith(b"\n")


def test_read_rejects_foreign_file(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"gate": "other"}', encoding="utf-8")
    with pytest.raises(baseline.BaselineError):
        baseline.read(path)


def test_read_rejects_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(baseline.BaselineError):
        baseline.read(path)


def test_diff_reports_new_and_fixed() -> None:
    old = [make(msg="old"), make(rule="SG004", msg="dup")]
    new = [make(msg="old"), make(rule="SG009", msg="clar")]
    accepted = {f.fingerprint() for f in old}
    fresh, fixed = baseline.diff(new, accepted)
    assert [f.rule for f in fresh] == ["SG009"]
    assert fixed == 1


def test_baseline_survives_inserted_lines(tmp_path: Path) -> None:
    feature = write_set(tmp_path, tasks=replace(CLEAN_TASKS, " (FR-002)", ""))
    first = evaluate(feature, tmp_path)
    path = tmp_path / "baseline.json"
    baseline.write(path, first.findings)

    # Insert a paragraph above the requirement: line numbers move, findings stay.
    spec = (feature / "spec.md").read_text(encoding="utf-8")
    spec = spec.replace(
        "### Functional Requirements",
        "An extra explanatory paragraph.\n\nAnd another one.\n\n### Functional Requirements",
    )
    (feature / "spec.md").write_text(spec, encoding="utf-8", newline="\n")

    second = evaluate(feature, tmp_path)
    fresh, fixed = baseline.diff(second.findings, baseline.read(path))
    assert fresh == []
    assert fixed == 0
    assert second.findings[0].line > first.findings[0].line
