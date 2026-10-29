"""Fixture builders for the gate tests.

Artifacts are written to a temporary project root instead of being committed as
fixtures: the interesting cases are *layouts*, and a test that shows the three
lines it depends on is easier to trust than a 200-line markdown file.
"""

from __future__ import annotations

from pathlib import Path

CLEAN_SPEC = """# Feature Specification: Widget sync

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sync a widget (Priority: P1)

A user syncs one widget.

**Why this priority**: it is the whole feature.

**Independent Test**: run the sync command.

**Acceptance Scenarios**:

1. **Given** a widget, **When** sync runs, **Then** the widget is stored.

---

### User Story 2 - List widgets (Priority: P2)

A user lists widgets.

**Why this priority**: read side of the same data.

**Independent Test**: run the list command.

**Acceptance Scenarios**:

1. **Given** a stored widget, **When** list runs, **Then** the widget appears.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST store a widget in `src/store.py`.
- **FR-002**: System MUST list stored widgets via `src/store.py`.

### Key Entities

- **Widget**: the stored thing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user syncs a widget in under 2 seconds.
"""

CLEAN_PLAN = """# Implementation Plan

FR-001 and FR-002 are implemented in `src/store.py`.

## Phase 0: Research

Nothing to research.
"""

CLEAN_TASKS = """# Tasks

## Phase 1: Setup

- [x] T001 Create project skeleton in `src/__init__.py`

## Phase 2: User Story 1 - Sync a widget (Priority: P1)

- [ ] T002 [P] [US1] Implement the store in `src/store.py` (FR-001)

## Phase 3: User Story 2 - List widgets (Priority: P2)

- [ ] T003 [US2] Implement listing in `src/store.py` (FR-002)

## Traceability

- SC-001 is measured by the sync benchmark.
"""

TASK_T003 = "- [ ] T003 [US2] Implement listing in `src/store.py` (FR-002)"
PHASE_US2 = "## Phase 3: User Story 2 - List widgets (Priority: P2)"


def write_set(
    root: Path,
    *,
    spec: str = CLEAN_SPEC,
    plan: str = CLEAN_PLAN,
    tasks: str = CLEAN_TASKS,
    directory: str = "specs/001-widget-sync",
    touch: tuple[str, ...] = ("src/__init__.py",),
) -> Path:
    """Write a feature directory under ``root`` and return the feature path."""
    feature = root / directory
    feature.mkdir(parents=True, exist_ok=True)
    (feature / "spec.md").write_text(spec, encoding="utf-8", newline="\n")
    (feature / "plan.md").write_text(plan, encoding="utf-8", newline="\n")
    (feature / "tasks.md").write_text(tasks, encoding="utf-8", newline="\n")
    for relative in touch:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    return feature


def replace(text: str, old: str, new: str) -> str:
    assert old in text, f"fixture drift: {old!r} not found"
    return text.replace(old, new)
