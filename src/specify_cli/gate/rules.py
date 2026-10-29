"""Rule implementations.

Every rule is a pure function of the parsed artifacts (plus, for the path rule,
the repo tree). No clocks, no network, no randomness — the same input must
produce byte-identical output, otherwise the gate cannot be used as a CI
baseline.

Rules are split into two tiers:

``core``
    Structural defects that make the artifact set *wrong*: duplicate ids,
    references to requirements that do not exist, requirements with no task,
    tasks claiming to be done whose file never appeared. These are always on.
``strict``
    Conformance to the format the shipped templates require. Useful for
    greenfield projects, noisy on mature ones, therefore opt-in via
    ``--strict``.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from .model import ArtifactSet, Finding
from .parse import blank_noise, clarifications, find_ids, placeholders


def _f(
    rule: str,
    severity: str,
    tier: str,
    artifact: str,
    line: int | None,
    message: str,
    subject: str | None = None,
    detail: dict[str, str] | None = None,
) -> Finding:
    return Finding(
        rule=rule,
        severity=severity,  # type: ignore[arg-type]
        tier=tier,  # type: ignore[arg-type]
        artifact=artifact,
        line=line,
        message=message,
        subject=subject,
        detail=detail or {},
    )


# ---------------------------------------------------------------------------
# core rules
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(
        None, _normalise(left)[:200], _normalise(right)[:200]
    ).ratio()


def rule_duplicate_requirements(a: ArtifactSet) -> list[Finding]:
    """The same id declared twice with the same words.

    A repeated id is *not* automatically a duplicate: some specs split one
    requirement over several aspect bullets (``- **FR-020 Component.** …``
    followed by ``- **FR-020 Behaviour.** …``). Those read as duplicates to a
    naive counter and were 45 % of this rule's corpus findings. The rule only
    fires when the two bodies say the same thing.
    """
    out: list[Finding] = []
    seen: dict[str, tuple[int, str]] = {}
    for req in a.requirements:
        first = seen.get(req.rid)
        if first is not None:
            if _similarity(first[1], req.text) < 0.6:
                continue
            out.append(
                _f(
                    "SG001",
                    "critical",
                    "core",
                    a.spec_path,
                    req.line,
                    f"requirement {req.rid} declared twice (first at line {first[0]})",
                    subject=req.rid,
                    detail={"first_line": str(first[0])},
                )
            )
        else:
            seen[req.rid] = (req.line, req.text)
    return out


def rule_dangling_task_refs(a: ArtifactSet) -> list[Finding]:
    """A task citing an id that ``spec.md`` never mentions.

    Deliberately *mention*-based, not *declaration*-based: a task may legitimately
    point at a sibling requirement that lives in a prose paragraph of the spec,
    and a gate that calls that dangling is wrong 80 % of the time (measured on
    71 corpus findings). What is left is the real failure: a typo or a
    renumbered id that exists nowhere.
    """
    known = {r.rid for r in a.requirements}
    spec_ids = set(find_ids(a.spec))
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for task in a.task_items:
        for rid in task.refs:
            if rid in known or rid in spec_ids or rid in a.sibling_ids:
                continue
            key = (task.tid or f"line{task.line}", rid)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                _f(
                    "SG002",
                    "high",
                    "core",
                    a.tasks_path,
                    task.line,
                    f"{task.tid or 'task'} references {rid}, which spec.md never mentions",
                    subject=rid,
                    detail={"task": task.tid or ""},
                )
            )
    return out


def rule_uncovered_requirements(
    a: ArtifactSet, coverage_encodable: bool, mode: str = "mention"
) -> list[Finding]:
    """Functional requirements with no trace in ``tasks.md``.

    Success criteria are handled by :func:`rule_uncovered_success_criteria`
    instead: ``/analyze`` itself says only criteria that "require buildable
    work" belong in the task list, so an outcome KPI with no task is expected,
    not a defect. Treating both the same inflated the corpus report by 276
    findings (46 % of the uncovered class).
    """
    if not coverage_encodable:
        return []
    out: list[Finding] = []
    for row in a.coverage_rows:
        if row.kind == "SC":
            continue
        if mode == "explicit" and row.channel == "explicit":
            continue
        if mode != "explicit" and row.channel != "none":
            continue
        where = "cited by a task" if mode == "explicit" else "mentioned anywhere"
        out.append(
            _f(
                "SG003",
                "high",
                "core",
                a.spec_path,
                row.line,
                f"{row.rid} is not {where} in {a.tasks_path}",
                subject=row.rid,
                detail={"text": row.text[:160]},
            )
        )
    return out


def rule_uncovered_success_criteria(
    a: ArtifactSet, coverage_encodable: bool
) -> list[Finding]:
    if not coverage_encodable:
        return []
    out: list[Finding] = []
    for row in a.coverage_rows:
        if row.channel != "none" or row.kind != "SC":
            continue
        out.append(
            _f(
                "SG012",
                "low",
                "core",
                a.spec_path,
                row.line,
                f"{row.rid} is not mentioned in {a.tasks_path} "
                "(expected for outcome-only metrics)",
                subject=row.rid,
                detail={"text": row.text[:160]},
            )
        )
    return out


def rule_duplicate_task_ids(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for task in a.task_items:
        if not task.tid:
            continue
        if task.tid in seen:
            out.append(
                _f(
                    "SG004",
                    "high",
                    "core",
                    a.tasks_path,
                    task.line,
                    f"task id {task.tid} reused (first at line {seen[task.tid]})",
                    subject=task.tid,
                    detail={"first_line": str(seen[task.tid])},
                )
            )
        else:
            seen[task.tid] = task.line
    return out


def rule_missing_task_id(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    for task in a.task_items:
        if task.tid is None:
            out.append(
                _f(
                    "SG006",
                    "medium",
                    "strict",
                    a.tasks_path,
                    task.line,
                    "task line has no T### id, so nothing can reference it",
                    detail={"text": task.text[:120]},
                )
            )
    return out


def rule_dangling_story_labels(a: ArtifactSet) -> list[Finding]:
    if not a.stories:
        return []
    known = {s.number for s in a.stories}
    out: list[Finding] = []
    for task in a.task_items:
        if task.story is None or task.story in known:
            continue
        out.append(
            _f(
                "SG007",
                "high",
                "core",
                a.tasks_path,
                task.line,
                f"{task.tid or 'task'} is labelled [US{task.story}] but spec.md has "
                f"{len(known)} user stories",
                subject=f"US{task.story}",
                detail={"task": task.tid or ""},
            )
        )
    return out


def rule_story_without_tasks(a: ArtifactSet) -> list[Finding]:
    if not a.stories:
        return []
    labelled = {t.story for t in a.task_items if t.story is not None}
    in_phase = {t.phase_story for t in a.task_items if t.phase_story is not None}
    covered = labelled | in_phase
    if not covered:
        # tasks.md does not use story labels or story phases at all: the
        # mapping is not encodable, so claiming a gap would be a guess.
        return []
    out: list[Finding] = []
    for story in a.stories:
        if story.number in covered:
            continue
        out.append(
            _f(
                "SG008",
                "medium",
                "core",
                a.spec_path,
                story.line,
                f"user story {story.number} ({story.title or 'untitled'}) has no task "
                f"labelled [US{story.number}] and no phase of its own",
                subject=f"US{story.number}",
            )
        )
    return out


def rule_unresolved_clarifications(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    for artifact, text, path in (
        ("spec", a.spec, a.spec_path),
        ("plan", a.plan, a.plan_path),
        ("tasks", a.tasks, a.tasks_path),
    ):
        for line_no, raw in clarifications(text):
            out.append(
                _f(
                    "SG009",
                    "high",
                    "core",
                    path,
                    line_no,
                    "unresolved [NEEDS CLARIFICATION] left in the artifact",
                    detail={"excerpt": raw[:160]},
                )
            )
    return out


def _normalize_path(token: str) -> str:
    token = token.strip().strip("`'\"")
    while token.startswith("./"):
        token = token[2:]
    return token


def rule_completed_task_missing_path(a: ArtifactSet) -> list[Finding]:
    """A task marked ``[x]`` whose declared files are absent from the tree.

    Only paths that name a *file* (they carry an extension) are considered: a
    task may also mention a directory, and a directory that was never created
    is a much weaker claim than "the file this task created does not exist".
    """
    if not a.root:
        return []
    root = Path(a.root)
    base = root / a.directory if a.directory else root
    out: list[Finding] = []
    for task in a.task_items:
        if not task.checked:
            continue
        files = [p for p in task.paths if re.search(r"\.[A-Za-z0-9]{1,8}$", p)]
        if not files:
            continue
        existing = [
            _normalize_path(token)
            for token in files
            if (base / _normalize_path(token)).exists()
            or (root / _normalize_path(token)).exists()
        ]
        if existing:
            continue
        out.append(
            _f(
                "SG010",
                "high",
                "core",
                a.tasks_path,
                task.line,
                f"{task.tid or 'task'} is marked done but none of its files exist: "
                + ", ".join(files[:3]),
                subject=task.tid,
                detail={"paths": ";".join(files[:5])},
            )
        )
    return out


def rule_plan_dangling_refs(a: ArtifactSet) -> list[Finding]:
    if not a.plan.strip() or not a.requirements:
        return []
    from .parse import find_ids

    known = set(find_ids(a.spec)) | set(a.sibling_ids)
    out: list[Finding] = []
    seen: set[str] = set()
    for idx, line in enumerate(blank_noise(a.plan), start=1):
        for rid in find_ids(line):
            if rid in known or rid in seen:
                continue
            seen.add(rid)
            out.append(
                _f(
                    "SG011",
                    "medium",
                    "core",
                    a.plan_path,
                    idx,
                    f"plan references {rid}, which spec.md never mentions",
                    subject=rid,
                )
            )
    return out


# ---------------------------------------------------------------------------
# strict rules (template conformance)
# ---------------------------------------------------------------------------


def rule_story_label_required(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    for task in a.task_items:
        if task.phase_is_story and task.story is None:
            out.append(
                _f(
                    "SG101",
                    "medium",
                    "strict",
                    a.tasks_path,
                    task.line,
                    f"{task.tid or 'task'} sits in a user-story phase but carries no "
                    "[USn] label",
                    subject=task.tid,
                    detail={"phase": task.phase or ""},
                )
            )
    return out


def rule_story_label_unexpected(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    for task in a.task_items:
        if (
            task.story is not None
            and task.phase is not None
            and not task.phase_is_story
        ):
            out.append(
                _f(
                    "SG102",
                    "low",
                    "strict",
                    a.tasks_path,
                    task.line,
                    f"{task.tid or 'task'} carries [US{task.story}] outside a user-story "
                    f"phase ({task.phase})",
                    subject=task.tid,
                )
            )
    return out


def rule_missing_file_path(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    for task in a.task_items:
        if not task.paths:
            out.append(
                _f(
                    "SG103",
                    "low",
                    "strict",
                    a.tasks_path,
                    task.line,
                    f"{task.tid or 'task'} names no file path",
                    subject=task.tid,
                    detail={"text": task.text[:120]},
                )
            )
    return out


def rule_phase_heading_missing(a: ArtifactSet) -> list[Finding]:
    if not a.task_items:
        return []
    if any(t.phase is not None for t in a.task_items):
        return []
    return [
        _f(
            "SG104",
            "medium",
            "strict",
            a.tasks_path,
            a.task_items[0].line,
            "tasks.md has tasks but no phase headings",
        )
    ]


def rule_acceptance_scenarios(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    for story in a.stories:
        if story.scenarios:
            continue
        out.append(
            _f(
                "SG105",
                "medium",
                "strict",
                a.spec_path,
                story.line,
                f"user story {story.number} has no Given/When/Then acceptance scenario",
                subject=f"US{story.number}",
            )
        )
    return out


def rule_story_metadata(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    for story in a.stories:
        missing = []
        if not story.has_why:
            missing.append("Why this priority")
        if not story.has_independent_test:
            missing.append("Independent Test")
        if not missing:
            continue
        out.append(
            _f(
                "SG106",
                "low",
                "strict",
                a.spec_path,
                story.line,
                f"user story {story.number} is missing: {', '.join(missing)}",
                subject=f"US{story.number}",
            )
        )
    return out


def rule_placeholders(a: ArtifactSet) -> list[Finding]:
    out: list[Finding] = []
    for text, path in (
        (a.spec, a.spec_path),
        (a.plan, a.plan_path),
        (a.tasks, a.tasks_path),
    ):
        for line_no, raw in placeholders(text):
            out.append(
                _f(
                    "SG107",
                    "low",
                    "strict",
                    path,
                    line_no,
                    "placeholder text left in the artifact",
                    detail={"excerpt": raw[:160]},
                )
            )
    return out


def rule_unsupported_layout(a: ArtifactSet) -> list[Finding]:
    """Report the gate's own blind spot instead of reporting success.

    Some specs declare requirements in a layout this parser does not recognise
    (custom prefixes, table-only declarations, unusual headings). Silence there
    would read as "nothing to report", which is the worst possible answer from
    an audit tool.
    """
    if a.requirements or a.spec_id_count < 3:
        return []
    return [
        _f(
            "SG013",
            "low",
            "core",
            a.spec_path,
            None,
            f"spec.md mentions {a.spec_id_count} requirement ids but none matches a "
            "recognised declaration layout; coverage is unavailable for this feature",
            detail={"ids_seen": str(a.spec_id_count)},
        )
    ]


CORE_RULES = (
    rule_duplicate_requirements,
    rule_dangling_task_refs,
    rule_duplicate_task_ids,
    rule_dangling_story_labels,
    rule_story_without_tasks,
    rule_unresolved_clarifications,
    rule_completed_task_missing_path,
    rule_plan_dangling_refs,
    rule_unsupported_layout,
)

STRICT_RULES = (
    rule_missing_task_id,
    rule_story_label_required,
    rule_story_label_unexpected,
    rule_missing_file_path,
    rule_phase_heading_missing,
    rule_acceptance_scenarios,
    rule_story_metadata,
    rule_placeholders,
)


def run_rules(
    a: ArtifactSet,
    *,
    strict: bool,
    coverage_encodable: bool,
    coverage_mode: str = "mention",
) -> list[Finding]:
    findings: list[Finding] = []
    for rule in CORE_RULES:
        findings.extend(rule(a))
    findings.extend(rule_uncovered_requirements(a, coverage_encodable, coverage_mode))
    findings.extend(rule_uncovered_success_criteria(a, coverage_encodable))
    if strict:
        for rule in STRICT_RULES:
            findings.extend(rule(a))
    return sort_findings(findings)


def sort_findings(findings: list[Finding]) -> list[Finding]:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        findings,
        key=lambda f: (f.artifact, f.line or 0, order[f.severity], f.rule, f.message),
    )
