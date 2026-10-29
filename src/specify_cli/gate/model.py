"""Data model for the Spec Kit conformance gate.

Every structure here is intentionally plain and immutable: the gate is a
*deterministic* checker, so the model must not carry any state that depends on
wall-clock time, filesystem order, or dict insertion order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["critical", "high", "medium", "low"]
Tier = Literal["core", "strict"]


@dataclass(frozen=True)
class Requirement:
    """A declared requirement / success criterion in ``spec.md``."""

    rid: str
    kind: str  # FR, NFR, SC, CR, TR
    number: int
    text: str
    line: int  # 1-based line number in the source artifact


@dataclass(frozen=True)
class UserStory:
    """A user story heading in ``spec.md``."""

    number: int
    title: str
    line: int
    scenarios: int  # number of Given/When/Then acceptance scenarios
    has_why: bool
    has_independent_test: bool


@dataclass(frozen=True)
class Task:
    """A task line in ``tasks.md`` (continuation lines are folded in)."""

    tid: str | None
    line: int
    end_line: int
    checked: bool
    parallel: bool
    story: int | None
    text: str
    raw: str
    phase: str | None
    phase_is_story: bool
    phase_story: int | None = None
    paths: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    """A single conformance finding."""

    rule: str
    severity: Severity
    tier: Tier
    artifact: str  # repo-relative POSIX path
    line: int | None
    message: str
    subject: str | None = None  # requirement id / task id the finding is about
    detail: dict[str, str] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Stable identity for baseline diffing.

        The line number is deliberately *not* part of the fingerprint: adding a
        paragraph above a defect must not turn an accepted finding into a "new"
        one, otherwise the CI baseline is worthless.
        """
        import hashlib

        parts = [self.rule, self.artifact, self.subject or "", self.message]
        blob = "\x1f".join(parts).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]


@dataclass
class RequirementCoverage:
    rid: str
    kind: str
    text: str
    line: int
    tasks: tuple[str, ...]
    channel: str  # "explicit" | "mention" | "none"
    mention_line: int | None = None


@dataclass
class ArtifactSet:
    """All artifacts of one feature directory, plus repo context."""

    root: str  # repo root (POSIX, absolute) or "" when unavailable
    directory: str  # feature dir relative to root ("" for root-level sets)
    spec: str = ""
    plan: str = ""
    tasks: str = ""
    constitution: str = ""
    spec_path: str = "spec.md"
    plan_path: str = "plan.md"
    tasks_path: str = "tasks.md"
    constitution_path: str = ""

    sibling_ids: frozenset[str] = frozenset()
    spec_id_count: int = 0
    requirements: list[Requirement] = field(default_factory=list)
    stories: list[UserStory] = field(default_factory=list)
    task_items: list[Task] = field(default_factory=list)
    coverage_rows: list[RequirementCoverage] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


@dataclass
class Report:
    """Machine-readable gate result."""

    version: str
    directory: str
    files: dict[str, str]
    findings: list[Finding]
    coverage: list[RequirementCoverage]
    metrics: dict[str, object]

    def counts(self) -> dict[str, int]:
        out = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in self.findings:
            out[f.severity] += 1
        return out
