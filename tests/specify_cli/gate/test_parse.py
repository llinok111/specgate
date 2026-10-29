"""Parser tests: the layouts that broke earlier drafts are pinned here."""

from __future__ import annotations

import pytest

from specify_cli.gate.parse import (
    blank_noise,
    clarifications,
    find_ids,
    parse_requirements,
    parse_stories,
    parse_tasks,
)


def ids(text: str) -> list[str]:
    return [r.rid for r in parse_requirements(text)]


class TestRequirementDeclarations:
    def test_colon_after_bold_is_a_declaration(self) -> None:
        text = "- **FR-001**: System MUST do the thing.\n"
        assert ids(text) == ["FR-001"]

    def test_no_separator_after_bold_is_a_declaration(self) -> None:
        # `- **FR-003** An unreachable BMC MUST yield UNKNOWN.`
        text = "## Requirements\n\n### Functional Requirements\n\n- **FR-003** Text.\n"
        assert ids(text) == ["FR-003"]

    def test_parenthesised_title_is_a_declaration(self) -> None:
        text = "## Requirements\n- **FR-001 (Motor hum looping)**: While true, MUST loop.\n"
        assert ids(text) == ["FR-001"]

    def test_bare_bold_paragraph_is_a_declaration(self) -> None:
        # Four spaces of indentation-free bold paragraph, no bullet at all.
        text = "## Requirements\n\n**FR-001**: The system MUST register tenants.\n"
        assert ids(text) == ["FR-001"]

    def test_reference_inside_a_sentence_is_not_a_declaration(self) -> None:
        text = (
            "## Requirements\n\n"
            "- **Two-drive motor**: both loops pan independently (FR-008).\n"
        )
        assert ids(text) == []

    def test_narrative_section_is_not_a_declaration(self) -> None:
        text = (
            "## Requirements\n\n"
            "### Functional Requirements\n\n"
            "- **FR-001**: Real.\n\n"
            "## Clarifications\n\n"
            "### Session 2026-07-17\n\n"
            "4. **FR-008 named a mechanism that does not exist.** It required X.\n"
        )
        assert ids(text) == ["FR-001"]

    def test_table_rows_are_not_declarations(self) -> None:
        text = (
            "## Requirements\n\n"
            "### Traceability\n\n"
            "| Requirement | Kind | Test |\n"
            "|---|---|---|\n"
            "| FR-004–FR-016 | Event-driven | UC-1 |\n"
        )
        assert ids(text) == []

    def test_combined_id_summary_is_not_three_declarations(self) -> None:
        text = (
            "## Requirements\n\n"
            "### Status\n\n"
            "- **FR-002/FR-004/FR-006** `[IMPLEMENTED]` in `src/store.ts`\n"
        )
        assert ids(text) == []

    def test_delta_entry_does_not_redeclare(self) -> None:
        text = (
            "## Requirements\n\n"
            "- **FR-005** Base behaviour.\n"
            "- **FR-005 delta**: the folders may change after a copy.\n"
        )
        assert ids(text) == ["FR-005"]

    def test_suffix_ids_are_distinct(self) -> None:
        text = (
            "## Requirements\n\n"
            "- **FR-096**: Base.\n"
            "- **FR-096a**: Arrow keys MUST scroll.\n"
            "- **FR-096b**: Home/End MUST scroll.\n"
        )
        assert ids(text) == ["FR-096", "FR-096a", "FR-096b"]

    def test_prefixed_ids_keep_their_prefix(self) -> None:
        text = "## Requirements\n\n### PDV\n\n### PDV-FR-001: CRUD de Vendas\n"
        assert ids(text) == ["PDV-FR-001"]

    def test_fenced_code_and_comments_are_ignored(self) -> None:
        text = (
            "## Requirements\n\n"
            "```\n- **FR-900**: example inside a fence\n```\n\n"
            "<!-- - **FR-901**: example inside a comment -->\n\n"
            "- **FR-001**: Real.\n"
        )
        assert ids(text) == ["FR-001"]

    def test_multi_line_comment_spanning_lines(self) -> None:
        text = (
            "## Requirements\n\n"
            "<!--\n- **FR-900**: example\n--> \n"
            "- **FR-001**: Real.\n"
        )
        assert ids(text) == ["FR-001"]


class TestReferences:
    def test_find_ids_normalises_numbers(self) -> None:
        assert find_ids("see FR-1 and FR-0001 and PDV-FR-007") == [
            "FR-001",
            "FR-001",
            "PDV-FR-007",
        ]

    def test_blank_noise_preserves_line_numbers(self) -> None:
        text = "a\n```\nb\n```\nc\n"
        lines = blank_noise(text)
        assert len(lines) == 5
        assert lines[0] == "a"
        assert lines[1] == ""
        assert lines[4] == "c"

    def test_clarification_marker(self) -> None:
        assert clarifications("- **FR-006**: auth via [NEEDS CLARIFICATION: which?]")
        assert clarifications("<!-- [NEEDS CLARIFICATION] -->") == []


class TestStories:
    def test_story_headings_and_scenarios(self) -> None:
        spec = (
            "### User Story 1 - Sync (Priority: P1)\n\n"
            "**Why this priority**: x\n\n**Independent Test**: y\n\n"
            "1. **Given** a, **When** b, **Then** c.\n\n"
            "### User Story 2 - List (Priority: P2)\n\n"
            "**Why this priority**: x\n\n**Independent Test**: y\n"
        )
        stories = parse_stories(spec)
        assert [s.number for s in stories] == [1, 2]
        assert stories[0].scenarios == 1
        assert stories[1].scenarios == 0
        assert stories[0].has_why and stories[0].has_independent_test

    def test_short_story_heading_form(self) -> None:
        stories = parse_stories("### US4: refs ignores digits (P2)\n")
        assert [(s.number, s.title) for s in stories] == [
            (4, "refs ignores digits (P2)")
        ]


class TestTasks:
    def test_basic_tasks_and_labels(self) -> None:
        tasks = parse_tasks(
            "## Phase 3: User Story 1 - Sync (Priority: P1)\n\n"
            "- [ ] T002 [P] [US1] Implement `src/store.py` (FR-001)\n"
        )
        assert len(tasks) == 1
        task = tasks[0]
        assert (task.tid, task.parallel, task.story, task.checked) == (
            "T002",
            True,
            1,
            False,
        )
        assert task.paths == ("src/store.py",)
        assert task.refs == ("FR-001",)
        assert task.phase_is_story and task.phase_story == 1

    def test_uppercase_checkbox_and_bold_id(self) -> None:
        tasks = parse_tasks("- [X] **T007** raises when asked (FR-003)\n")
        assert tasks[0].tid == "T007"
        assert tasks[0].checked is True

    def test_wrapped_description_is_folded(self) -> None:
        tasks = parse_tasks(
            "- [X] T001 Evaluate `a/b.py` — no licence at all,\n"
            "      unvendorable (FR-001)\n"
        )
        assert tasks[0].refs == ("FR-001",)
        assert "unvendorable" in tasks[0].raw

    def test_indented_checkbox_is_not_a_task(self) -> None:
        tasks = parse_tasks(
            "- [ ] T001 Do the thing in `src/a.py`\n  - [ ] acceptance bullet\n"
        )
        assert [t.tid for t in tasks] == ["T001"]

    def test_sub_numbered_ids_stay_distinct(self) -> None:
        tasks = parse_tasks(
            "- [ ] T009c-2 [US1] First in `a.py`\n- [ ] T009c-5 [US1] Second in `a.py`\n"
        )
        assert [t.tid for t in tasks] == ["T009c-2", "T009c-5"]

    def test_task_without_id(self) -> None:
        tasks = parse_tasks("- [x] **0.1** [Setup] Add a dependency\n")
        assert tasks[0].tid is None

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("- [ ] T001 Create `a/b.py`", ("a/b.py",)),
            ("- [ ] T001 Touch `x`", ()),
            ("- [ ] T001 Update `docs/<name>.md`", ()),
            ("- [ ] T001 See https://example.com/x.py", ()),
        ],
    )
    def test_path_extraction(self, line: str, expected: tuple[str, ...]) -> None:
        assert parse_tasks(line)[0].paths == expected
