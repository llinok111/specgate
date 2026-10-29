"""Deterministic markdown parsing for Spec Kit artifacts.

The parser is deliberately conservative. Spec Kit artifacts are hand- and
LLM-written prose, so the only safe assumption is: *a requirement/task exists
where the template says it does* — a line that opens with an identifier. Any
identifier that merely appears inside a sentence is treated as a reference,
never as a declaration.

Two kinds of noise are stripped before anything is parsed, because the shipped
templates are full of them:

* fenced code blocks (```` ``` ````) — they contain example task lists,
* HTML comments (``<!-- ... -->``) — they contain example requirements and
  ``[NEEDS CLARIFICATION]`` placeholders.

Lines are replaced by blanks instead of being removed so that every reported
line number still points at the original file.
"""

from __future__ import annotations

import re

from .model import Requirement, Task, UserStory

# ---------------------------------------------------------------------------
# Identifier grammars
# ---------------------------------------------------------------------------

KINDS = ("NFR", "FR", "SC", "CR", "TR")

# A requirement id is ``FR-001`` or a project-prefixed variant such as
# ``PDV-FR-001``. The prefix is part of the identity: dropping it merges two
# different requirement sets in repos that scope ids per module.
_ID = (
    r"(?:(?P<prefix>[A-Z][A-Z0-9]{1,7})-)?"
    r"(?P<kind>NFR|FR|SC|CR|TR)-(?P<num>\d{1,4})(?P<suffix>[a-z])?(?!\d)"
)

ID_RE = re.compile(r"\b" + _ID + r"\b")

DECL_RE = re.compile(
    r"^\s*\|?\s*(?:[-*+]\s+)?(?:\*\*|__)?\s*" + _ID + r"\s*(?:\*\*|__)?\s*(?P<rest>.*)$"
)


def format_id(
    kind: str, num: int, suffix: str | None = None, prefix: str | None = None
) -> str:
    """Canonical id: ``FR-015c`` keeps its lower-case suffix, ``PDV-FR-001``
    keeps its prefix.

    Real specs sub-divide requirements (``FR-096a``, ``FR-016b``) instead of
    renumbering. Dropping the suffix merges distinct requirements into one and
    turns every sibling into a phantom duplicate — 83 of them on the first
    corpus run.
    """
    head = f"{prefix}-" if prefix else ""
    return f"{head}{kind}-{num:03d}{suffix or ''}"


TASK_LINE_RE = re.compile(
    r"^(?P<indent>\s*)[-*+]\s+\[(?P<check>[ xX])\]\s*(?P<rest>.*)$"
)

TASK_ID_PREFIX_RE = re.compile(
    r"^(?:\*\*|__)?"
    # ``T015``, ``T015a``, ``T009c-2``, ``T026A``, ``T032-REF`` — but never
    # ``T001-T004``, which is a task *range*: the negative lookahead keeps the
    # range text from being read as the id ``T001-T``.
    r"(?P<tid>T\d{2,4}(?:[a-zA-Z](?:[-.]\d{1,2}[a-z]?)?|[-.]\d{1,2}[a-z]?|-(?!T\d)[A-Za-z]{1,6})?)"
    r"(?:\*\*|__)?"
)

TASK_RANGE_RE = re.compile(r"^T\d{2,4}\s*[-\u2013\u2014]\s*T\d{2,4}(?!\d)")

LABEL_RE = re.compile(r"\[(?P<label>P|US\s?\d{1,2}|Story\s?\d{1,2})\]")

STORY_HEADING_RE = re.compile(
    r"^#{2,5}\s+User\s+Story\s+(?P<num>\d{1,3})\b(?P<rest>.*)$", re.IGNORECASE
)
STORY_HEADING_ALT_RE = re.compile(
    r"^#{2,5}\s+US[-\s]?(?P<num>\d{1,3})\b(?P<rest>.*)$", re.IGNORECASE
)
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")

SCENARIO_RE = re.compile(
    r"\*\*Given\*\*|\bGiven\b.*\bWhen\b.*\bThen\b|^\s*\d+\.\s+\*?\*?Given", re.I
)
CLARIFY_RE = re.compile(r"\[\s*NEEDS\s+CLARIFICATION", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(
    r"\b(TKTK|TBD|TODO|XXX|FIXME)\b|\?\?\?|\[(?:[A-Z][A-Za-z ]{2,30})\]"
)

# Path-ish tokens: quoted/backticked first, then bare tokens with a known extension.
BACKTICK_PATH_RE = re.compile(r"`([^`\n]{1,200})`")
BARE_PATH_RE = re.compile(
    r"(?<![\w/.-])("
    r"(?:\.{1,2}/)?(?:[\w.@+-]+/)+[\w.@+\-]*"
    r"|[\w.@+\-]+"
    r")\.("
    r"py|pyi|ts|tsx|js|jsx|mjs|cjs|vue|svelte|go|rs|java|kt|kts|rb|php|cs|c|h|cc|cpp|hpp"
    r"|swift|dart|sh|bash|ps1|psm1|sql|md|json|json5|ya?ml|toml|ini|cfg|conf|env|lock"
    r"|css|scss|sass|less|html|htm|xml|svg|proto|graphql|gql|tf|gradle|properties"
    r"|txt|csv|parquet|ipynb"
    r")\b"
)

PLACEHOLDERS = ("<", ">", "{", "}", "*", "...", "$", "%", "|")


# ---------------------------------------------------------------------------
# Noise stripping
# ---------------------------------------------------------------------------


def blank_noise(text: str) -> list[str]:
    """Return lines with fenced code blocks and HTML comments blanked out."""
    lines = text.splitlines()
    out: list[str] = []
    fence: str | None = None
    in_comment = False
    for line in lines:
        stripped = line.strip()

        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            out.append("")
            continue

        if in_comment:
            if "-->" in stripped:
                in_comment = False
            out.append("")
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            out.append("")
            continue

        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            out.append("")
            continue

        out.append(line)

    return out


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------


REQUIREMENT_SECTION_RE = re.compile(
    r"requirement|success\s+criteria|success\s+criteri|acceptance\s+criteria"
    r"|measurable\s+outcome|functional|non-functional|constraint|traceab",
    re.IGNORECASE,
)

# Sections that reuse requirement ids in prose ("4. **FR-008 named a mechanism
# that does not exist.**"). Their content is narrative, never a declaration.
NARRATIVE_SECTION_RE = re.compile(
    r"\breview\b|review\s+notes|change\s*log|history|defects?\b|defect\s+list"
    r"|open\s+questions?|assumptions?|risks?\b|narrative|retrospective|appendix"
    r"|lessons|clarif|session|discussion|decision\s+log|背景|变更|复盘",
    re.IGNORECASE,
)


def parse_requirements(text: str, artifact: str = "spec.md") -> list[Requirement]:
    """Extract requirement declarations.

    Two signals are combined, because neither alone survives real specs:

    1. **Position** — the identifier must open the item (after an optional
       bullet, table pipe, ordered-list number or bold marker). An identifier
       inside a sentence (``... both loops pan (FR-008).``) is a reference.
    2. **Section** — the item must sit under a requirements / success-criteria
       heading and not under a narrative one. Narrative sections reuse the same
       ids in prose and would otherwise register as duplicate declarations.

    When a spec has no recognisable requirements heading at all, signal 2 is
    dropped rather than rejecting every requirement in the file.
    """
    lines = blank_noise(text)
    has_requirement_section = any(
        HEADING_RE.match(line) and REQUIREMENT_SECTION_RE.search(line) for line in lines
    )
    reqs: list[Requirement] = []
    stack: list[tuple[int, str]] = []  # (heading level, title)
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        heading = HEADING_RE.match(stripped)
        is_item = False
        candidate = stripped
        if heading:
            level = len(heading.group("hashes"))
            title = heading.group("title")
            candidate = title
            is_item = True
            if not re.match(
                r"^(?:\*\*|__)?\s*(?:[A-Z][A-Z0-9]{1,7}-)?(?:NFR|FR|SC|CR|TR)-\d",
                candidate,
            ):
                # A normal heading: it opens a new section at this level.
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
        else:
            item = re.match(r"^(?:[-*+]\s+|\d+[.)]\s+|\|\s*)", candidate)
            if item:
                candidate = candidate[item.end() :]
                is_item = True

        if stripped.startswith("|"):
            # Table rows are traceability matrices in practice
            # (``| FR-004–FR-016 | Event-driven | UC-AA-09 |``), not
            # declarations. Excluding them removed every phantom duplicate in
            # the corpus; the ids are still visible as references.
            continue

        titles = [title for _, title in stack]
        if any(NARRATIVE_SECTION_RE.search(title) for title in titles):
            # A narrative ancestor vetoes, even inside a requirements section:
            # "## Requirements … ### Defect review" quotes ids in prose.
            in_requirement_section = False
        elif any(REQUIREMENT_SECTION_RE.search(title) for title in titles):
            in_requirement_section = True
        else:
            in_requirement_section = not has_requirement_section

        m = re.match(
            r"^(?:\*\*|__)?\s*" + _ID,
            candidate,
        )
        if not m:
            continue
        if not in_requirement_section:
            continue
        tail = candidate[m.end() :]
        # Drop the *closing* bold marker the identifier regex stopped in front
        # of: ``**FR-001**: text`` is a declaration, not a reference.
        closing = tail.lstrip()
        if closing.startswith(("**", "__")):
            closing = closing[2:]
        if not is_item and not re.match(r"^\s*(?:[:：\-–—|]|$)", closing):
            # Plain paragraph that merely starts with an id: a reference.
            continue
        if re.match(
            r"^\s*(?:\*\*|__)?\s*/\s*(?:[A-Z][A-Z0-9]{1,7}-)?(?:NFR|FR|SC|CR|TR)-\d",
            tail,
        ):
            # ``- **FR-002/FR-004/FR-006** [IMPLEMENTED] ...`` is a traceability
            # summary of three requirements, not three declarations.
            continue
        if re.match(
            r"^\s*(?:\*\*|__)?\s*(?:delta|amendment|addendum|update|revised)\b",
            closing,
            re.I,
        ):
            # ``- **FR-005 delta** [IMPLEMENTED] ...`` amends a requirement; it
            # does not declare a second one.
            continue

        rid = format_id(
            m.group("kind"), int(m.group("num")), m.group("suffix"), m.group("prefix")
        )
        body = closing
        if body.startswith(("**", "__")):
            body = body[2:]
        body = body.lstrip(":：-–—| ").strip()
        body = body.strip("*_ ").strip()
        reqs.append(
            Requirement(
                rid=rid,
                kind=m.group("kind"),
                number=int(m.group("num")),
                text=body,
                line=idx,
            )
        )
    return reqs


def find_ids(text: str) -> list[str]:
    return [
        format_id(
            m.group("kind"), int(m.group("num")), m.group("suffix"), m.group("prefix")
        )
        for m in ID_RE.finditer(text)
    ]


# ---------------------------------------------------------------------------
# User stories
# ---------------------------------------------------------------------------


def parse_stories(text: str) -> list[UserStory]:
    lines = blank_noise(text)
    starts: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines, start=1):
        m = STORY_HEADING_RE.match(line) or STORY_HEADING_ALT_RE.match(line)
        if m:
            title = m.group("rest").strip(" -–—:")
            title = re.sub(r"^[-–—:]\s*", "", title)
            starts.append((idx, int(m.group("num")), title))
        elif HEADING_RE.match(line) and starts:
            # a same-or-higher level heading ends the current story block
            pass
    stories: list[UserStory] = []
    for pos, (line_no, num, title) in enumerate(starts):
        end = starts[pos + 1][0] - 1 if pos + 1 < len(starts) else len(lines)
        block = lines[line_no - 1 : end]
        scenarios = sum(1 for ln in block if SCENARIO_RE.search(ln))
        joined = "\n".join(block).lower()
        stories.append(
            UserStory(
                number=num,
                title=title,
                line=line_no,
                scenarios=scenarios,
                has_why="why this priority" in joined,
                has_independent_test="independent test" in joined,
            )
        )
    return stories


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def _extract_paths(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for m in BACKTICK_PATH_RE.finditer(text):
        token = m.group(1).strip()
        if "/" in token or re.search(r"\.[A-Za-z0-9]{1,8}$", token):
            found.append(token)
    for m in BARE_PATH_RE.finditer(text):
        found.append(m.group(0))
    cleaned: list[str] = []
    for token in found:
        token = token.strip().strip("`'\"(),;:")
        if not token or any(p in token for p in PLACEHOLDERS):
            continue
        if token.startswith(("http://", "https://", "www.")):
            continue
        if token.endswith((".md",)) and token in {"README.md"}:
            pass
        if token not in cleaned:
            cleaned.append(token)
    return tuple(cleaned)


def parse_tasks(text: str) -> list[Task]:
    lines = blank_noise(text)
    phase: str | None = None
    phase_is_story = False
    phase_story: int | None = None
    tasks: list[Task] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = HEADING_RE.match(line)
        if heading:
            phase = heading.group("title").strip()
            story_ref = re.search(
                r"\buser\s+story\s+(\d+)", phase, re.IGNORECASE
            ) or re.search(r"\bUS[-\s]?(\d+)\b", phase, re.IGNORECASE)
            phase_story = int(story_ref.group(1)) if story_ref else None
            phase_is_story = phase_story is not None and not re.search(
                r"polish|cross-cutting", phase, re.IGNORECASE
            )
            i += 1
            continue

        m = TASK_LINE_RE.match(line)
        if not m:
            i += 1
            continue

        if len(m.group("indent")) >= 2:
            # An indented checkbox is a sub-step of the task above it, not a
            # task: real tasks.md files use it for acceptance bullets.
            i += 1
            continue

        start = i
        rest = m.group("rest").rstrip()
        raw_parts = [rest]
        i += 1
        # Fold wrapped continuation lines (indented, not a new checkbox/heading).
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                break
            if TASK_LINE_RE.match(nxt) or HEADING_RE.match(nxt):
                break
            if nxt.startswith(("  ", "\t")) and nxt.strip():
                raw_parts.append(nxt.strip())
                i += 1
                continue
            break

        body = " ".join(p.strip() for p in raw_parts if p.strip())
        tid_m = TASK_ID_PREFIX_RE.match(body)
        if tid_m and TASK_RANGE_RE.match(body):
            # ``- [x] T001-T004 — All complete`` summarises four tasks; it is
            # not a task with the id ``T001``.
            tid_m = None
        tid = tid_m.group("tid") if tid_m else None
        after = body[tid_m.end() :] if tid_m else body

        parallel = bool(re.search(r"\[P\]", after))
        story_m = re.search(r"\[(?:US|Story)\s?(\d{1,2})\]", after)
        story = int(story_m.group(1)) if story_m else None
        desc = LABEL_RE.sub(" ", after)
        desc = re.sub(r"\s+", " ", desc).strip(" -–—:")

        tasks.append(
            Task(
                tid=tid,
                line=start + 1,
                end_line=i,
                checked=m.group("check").lower() == "x",
                parallel=parallel,
                story=story,
                text=desc,
                raw=body,
                phase=phase,
                phase_is_story=phase_is_story,
                phase_story=phase_story,
                paths=_extract_paths(body),
                refs=tuple(dict.fromkeys(find_ids(body))),
            )
        )
    return tasks


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def clarifications(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(blank_noise(text), start=1):
        if CLARIFY_RE.search(line):
            out.append((idx, line.strip()))
    return out


def placeholders(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(blank_noise(text), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if PLACEHOLDER_RE.search(stripped) and not stripped.startswith("#"):
            out.append((idx, stripped))
    return out
