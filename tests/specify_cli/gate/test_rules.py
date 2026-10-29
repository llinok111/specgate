"""Rule tests: every rule must fire on its defect and stay quiet on the clean set."""

from __future__ import annotations

from pathlib import Path

from specify_cli.gate.engine import evaluate

from .builders import CLEAN_PLAN, CLEAN_SPEC, CLEAN_TASKS, PHASE_US2, replace, write_set


def rules_at(root: Path, feature: Path, **kwargs) -> list[str]:
    report = evaluate(feature, root, **kwargs)
    return [f.rule for f in report.findings]


def test_clean_set_has_no_findings(tmp_path: Path) -> None:
    feature = write_set(tmp_path)
    report = evaluate(feature, tmp_path, strict=True)
    assert report.findings == [], [f.message for f in report.findings]
    assert report.metrics["requirements"] == 3
    assert report.metrics["tasks"] == 3
    assert report.metrics["coverage_pct"] == 100.0


def test_sg001_duplicate_requirement(tmp_path: Path) -> None:
    spec = replace(
        CLEAN_SPEC,
        "- **FR-002**: System MUST list stored widgets via `src/store.py`.",
        "- **FR-002**: System MUST list stored widgets via `src/store.py`.\n"
        "- **FR-002**: System MUST list stored widgets via `src/store.py`.",
    )
    feature = write_set(tmp_path, spec=spec)
    report = evaluate(feature, tmp_path)
    dupes = [f for f in report.findings if f.rule == "SG001"]
    assert len(dupes) == 1
    assert dupes[0].severity == "critical"


def test_sg001_ignores_split_aspect_bullets(tmp_path: Path) -> None:
    spec = replace(
        CLEAN_SPEC,
        "- **FR-002**: System MUST list stored widgets via `src/store.py`.",
        "- **FR-002 Component.** listing lives in `src/store.py`.\n"
        "- **FR-002 Behaviour.** the list is ordered by name.",
    )
    feature = write_set(
        tmp_path, spec=spec, tasks=replace(CLEAN_TASKS, "FR-002", "FR-002")
    )
    report = evaluate(feature, tmp_path)
    assert "SG001" not in [f.rule for f in report.findings]


def test_sg002_dangling_task_reference(tmp_path: Path) -> None:
    tasks = replace(CLEAN_TASKS, "(FR-001)", "(FR-777)")
    feature = write_set(tmp_path, tasks=tasks)
    report = evaluate(feature, tmp_path)
    dangling = [f for f in report.findings if f.rule == "SG002"]
    assert len(dangling) == 1
    assert dangling[0].subject == "FR-777"


def test_sg002_allows_reference_to_sibling_feature(tmp_path: Path) -> None:
    write_set(
        tmp_path,
        spec="# Sibling\n\n## Requirements\n\n- **FR-777**: Exists in feature 002.\n",
        tasks="# Tasks\n\n- [ ] T001 Do it\n",
        directory="specs/002-sibling",
    )
    feature = write_set(tmp_path, tasks=replace(CLEAN_TASKS, "(FR-001)", "(FR-777)"))
    report = evaluate(feature, tmp_path)
    assert "SG002" not in [f.rule for f in report.findings]


def test_sg003_uncovered_requirement(tmp_path: Path) -> None:
    tasks = replace(CLEAN_TASKS, " (FR-002)", "")
    feature = write_set(tmp_path, tasks=tasks)
    report = evaluate(feature, tmp_path)
    uncovered = [f for f in report.findings if f.rule == "SG003"]
    assert [f.subject for f in uncovered] == ["FR-002"]


def test_sg003_counts_mentions_outside_task_lines(tmp_path: Path) -> None:
    tasks = CLEAN_TASKS.replace("in `src/store.py` (FR-002)", "in `src/store.py`")
    tasks = tasks.replace(PHASE_US2, PHASE_US2 + " (FR-002)")
    feature = write_set(tmp_path, tasks=tasks)
    report = evaluate(feature, tmp_path)
    rows = {c.rid: c for c in report.coverage}
    assert rows["FR-002"].channel == "mention"
    assert "SG003" not in [f.rule for f in report.findings]


def test_sg003_explicit_mode_flags_mentions_only(tmp_path: Path) -> None:
    tasks = replace(CLEAN_TASKS, " (FR-002)", "")
    feature = write_set(tmp_path, tasks=tasks)
    report = evaluate(feature, tmp_path, coverage_mode="explicit")
    assert [f.subject for f in report.findings if f.rule == "SG003"] == ["FR-002"]


def test_sg004_duplicate_task_id(tmp_path: Path) -> None:
    tasks = replace(CLEAN_TASKS, "T003 [US2]", "T002 [US2]")
    feature = write_set(tmp_path, tasks=tasks)
    report = evaluate(feature, tmp_path)
    dupes = [f for f in report.findings if f.rule == "SG004"]
    assert len(dupes) == 1 and dupes[0].subject == "T002"


def test_sg007_story_label_without_story(tmp_path: Path) -> None:
    tasks = replace(CLEAN_TASKS, "[US2] Implement listing", "[US9] Implement listing")
    feature = write_set(tmp_path, tasks=tasks)
    report = evaluate(feature, tmp_path)
    found = [f for f in report.findings if f.rule == "SG007"]
    assert len(found) == 1 and found[0].subject == "US9"


def test_sg008_story_without_tasks(tmp_path: Path) -> None:
    tasks = replace(
        CLEAN_TASKS,
        "## Phase 3: User Story 2 - List widgets (Priority: P2)\n\n- [ ] T003 [US2] Implement listing in `src/store.py` (FR-002)\n",
        "",
    )
    feature = write_set(tmp_path, tasks=tasks)
    report = evaluate(feature, tmp_path)
    found = [f for f in report.findings if f.rule == "SG008"]
    assert [f.subject for f in found] == ["US2"]


def test_sg009_unresolved_clarification(tmp_path: Path) -> None:
    spec = replace(
        CLEAN_SPEC,
        "System MUST list stored widgets via `src/store.py`.",
        "System MUST authenticate via [NEEDS CLARIFICATION: which method?].",
    )
    feature = write_set(tmp_path, spec=spec)
    report = evaluate(feature, tmp_path)
    assert [f.rule for f in report.findings if f.rule == "SG009"] == ["SG009"]


def test_sg010_completed_task_file_absent(tmp_path: Path) -> None:
    tasks = replace(
        CLEAN_TASKS,
        "- [ ] T003 [US2] Implement listing in `src/store.py` (FR-002)",
        "- [x] T003 [US2] Implement listing in `src/missing.py` (FR-002)",
    )
    feature = write_set(tmp_path, tasks=tasks)
    report = evaluate(feature, tmp_path)
    found = [f for f in report.findings if f.rule == "SG010"]
    assert len(found) == 1 and found[0].subject == "T003"


def test_sg010_skips_unfinished_tasks(tmp_path: Path) -> None:
    tasks = replace(
        CLEAN_TASKS,
        "- [ ] T003 [US2] Implement listing in `src/store.py` (FR-002)",
        "- [ ] T003 [US2] Implement listing in `src/missing.py` (FR-002)",
    )
    feature = write_set(tmp_path, tasks=tasks)
    assert "SG010" not in [f.rule for f in evaluate(feature, tmp_path).findings]


def test_sg010_can_be_disabled(tmp_path: Path) -> None:
    tasks = replace(CLEAN_TASKS, "`src/store.py` (FR-002)", "`src/gone.py` (FR-002)")
    tasks = replace(tasks, "- [ ] T003 [US2]", "- [x] T003 [US2]")
    feature = write_set(tmp_path, tasks=tasks)
    assert "SG010" in rules_at(tmp_path, feature)
    assert "SG010" not in rules_at(tmp_path, feature, check_paths=False)


def test_sg011_plan_references_unknown_requirement(tmp_path: Path) -> None:
    plan = replace(CLEAN_PLAN, "FR-002 are implemented", "FR-902 are implemented")
    feature = write_set(tmp_path, plan=plan)
    report = evaluate(feature, tmp_path)
    assert [f.subject for f in report.findings if f.rule == "SG011"] == ["FR-902"]


def test_sg013_reports_unparseable_layout(tmp_path: Path) -> None:
    spec = (
        "# Spec\n\n## Requirements\n\n"
        "| Id | Text |\n|---|---|\n"
        "| FR-001 | store |\n| FR-002 | list |\n| FR-003 | delete |\n"
    )
    feature = write_set(tmp_path, spec=spec)
    report = evaluate(feature, tmp_path)
    found = [f for f in report.findings if f.rule == "SG013"]
    assert len(found) == 1
    assert report.metrics["coverage_encodable"] is False


def test_strict_rules_are_opt_in(tmp_path: Path) -> None:
    tasks = replace(
        CLEAN_TASKS,
        "- [ ] T002 [P] [US1] Implement the store in `src/store.py` (FR-001)",
        "- [ ] T002 [US1] Implement the store (FR-001)",
    )
    feature = write_set(tmp_path, tasks=tasks)
    assert "SG103" not in rules_at(tmp_path, feature)
    assert "SG103" in rules_at(tmp_path, feature, strict=True)


def test_strict_story_label_inside_plain_phase(tmp_path: Path) -> None:
    tasks = replace(
        CLEAN_TASKS,
        "- [x] T001 Create project skeleton in `src/__init__.py`",
        "- [x] T001 [US1] Create project skeleton in `src/__init__.py`",
    )
    feature = write_set(tmp_path, tasks=tasks)
    assert "SG102" in rules_at(tmp_path, feature, strict=True)


def test_strict_acceptance_scenarios(tmp_path: Path) -> None:
    spec = replace(
        CLEAN_SPEC,
        "**Acceptance Scenarios**:\n\n1. **Given** a widget, **When** sync runs, **Then** the widget is stored.\n",
        "",
    )
    feature = write_set(tmp_path, spec=spec)
    report = evaluate(feature, tmp_path, strict=True)
    assert [f.subject for f in report.findings if f.rule == "SG105"] == ["US1"]
