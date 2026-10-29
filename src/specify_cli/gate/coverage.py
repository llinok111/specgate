"""Requirement ⇄ task traceability, computed without guessing.

Spec Kit's ``/analyze`` prompt asks the model to "map each task to one or more
requirements or stories (inference by keyword / explicit reference patterns)".
Inference is exactly what a gate cannot do reproducibly, so this module only
uses text that is actually present, and it says which channel it used:

``explicit``
    a task line cites the id (``- [ ] T012 ... (FR-003)``). Strongest signal.
``mention``
    the id appears somewhere in ``tasks.md`` but not on a task line — a phase
    heading (``### T024b — Authorization check (FR-010 ...)``), a traceability
    table, or prose. Weaker but real: measured on the corpus, counting mentions
    as coverage removed 112 of 545 uncovered-requirement findings, because
    those ids *are* accounted for, just not on a checkbox line.
``none``
    the id appears nowhere in ``tasks.md``.

Percentages are only produced when the artifact set carries links at all. A
spec with zero citations gets ``coverage: null`` plus an explicit reason
instead of a fake 0 % (or a fake 100 %).
"""

from __future__ import annotations

import re

from .model import ArtifactSet, RequirementCoverage
from .parse import blank_noise, find_ids


def _mentions(text: str) -> dict[str, int]:
    seen: dict[str, int] = {}
    for idx, line in enumerate(blank_noise(text), start=1):
        for rid in find_ids(line):
            seen.setdefault(rid, idx)
    return seen


def build_coverage(
    artifacts: ArtifactSet,
) -> tuple[list[RequirementCoverage], dict[str, object]]:
    reqs = artifacts.requirements
    tasks = artifacts.task_items
    by_req: dict[str, list[str]] = {r.rid: [] for r in reqs}

    linked_tasks = 0
    for task in tasks:
        if not task.refs:
            continue
        linked_tasks += 1
        label = task.tid or f"line{task.line}"
        for rid in task.refs:
            if rid in by_req:
                by_req[rid].append(label)

    mentions = _mentions(artifacts.tasks)

    coverage: list[RequirementCoverage] = []
    for req in reqs:
        hits = tuple(dict.fromkeys(by_req[req.rid]))
        if hits:
            channel, mention_line = "explicit", None
        elif req.rid in mentions:
            channel, mention_line = "mention", mentions[req.rid]
        else:
            channel, mention_line = "none", None
        coverage.append(
            RequirementCoverage(
                rid=req.rid,
                kind=req.kind,
                text=req.text,
                line=req.line,
                tasks=hits,
                channel=channel,
                mention_line=mention_line,
            )
        )

    total = len(reqs)
    explicit = sum(1 for c in coverage if c.channel == "explicit")
    mentioned = sum(1 for c in coverage if c.channel != "none")
    encodable = total > 0 and (linked_tasks > 0 or mentioned > 0)

    story_tasks: dict[int, int] = {}
    for task in tasks:
        if task.story is not None:
            story_tasks[task.story] = story_tasks.get(task.story, 0) + 1
    stories = [s.number for s in artifacts.stories]
    stories_covered = sorted(n for n in stories if story_tasks.get(n))

    # Task ids out of ascending order are a metric, not a finding: real
    # tasks.md files splice a "repair cycle" phase into the middle (measured:
    # 57 order regressions in one real repository), so calling that a defect
    # would drown the report in noise.
    order_violations = 0
    prev: int | None = None
    for task in tasks:
        if not task.tid:
            continue
        head = re.match(r"T(\d+)", task.tid)
        num = int(head.group(1)) if head else 0
        if prev is not None and num < prev:
            order_violations += 1
        else:
            prev = num

    metrics: dict[str, object] = {
        "requirements": total,
        "tasks": len(tasks),
        "tasks_with_refs": linked_tasks,
        "link_density": round(linked_tasks / len(tasks), 4) if tasks else 0.0,
        "coverage_encodable": encodable,
        "requirements_explicit": explicit,
        "requirements_traced": mentioned,
        "coverage_pct": round(100.0 * mentioned / total, 2)
        if encodable and total
        else None,
        "coverage_pct_explicit": round(100.0 * explicit / total, 2) if total else None,
        "stories": len(stories),
        "stories_covered": len(stories_covered),
        "story_task_counts": {str(k): v for k, v in sorted(story_tasks.items())},
        "order_violations": order_violations,
    }
    if total and not encodable:
        metrics["coverage_reason"] = (
            "tasks.md never mentions a requirement id; coverage cannot be derived"
        )
    return coverage, metrics
