# `specify gate` — a deterministic conformance gate for Spec Kit artifacts

Spec Kit's `/analyze` command asks a language model to compare `spec.md`,
`plan.md` and `tasks.md`. The *prompt* is good; the *output* is not reproducible.
Re-running it on an unchanged repository produces a different report — that is
what upstream issue [#543](https://github.com/github/spec-kit/issues/543)
describes ("every new `/analyze` finds new CRITICAL issues"), and
[#3752](https://github.com/github/spec-kit/issues/3752) names the consequence:
convergence can be declared "without auditable acceptance-scenario coverage".

A check that flips between red and green for the same commit cannot gate CI.
`specify gate` implements the *mechanical* half of that analysis — the part with
an unambiguous answer — so that the answer is the same on every machine, in
every run:

```bash
specify gate                      # scan the current project
specify gate specs/003-payments   # scan one feature
specify gate --format json        # machine-readable
specify gate --format sarif       # GitHub code scanning
specify gate --strict             # also enforce the template's checklist format
```

Exit codes are a contract: `0` clean, `1` findings at or above `--fail-on`
(default `high`), `2` usage or I/O error, `3` unusable baseline.

## What it checks

| Rule | Tier | Severity | Fails when |
|---|---|---|---|
| SG001 | core | critical | the same requirement id is declared twice with the same words |
| SG002 | core | high | a task cites a requirement id that `spec.md` never mentions (typo, renumbering) |
| SG003 | core | high | a functional requirement is not mentioned anywhere in `tasks.md` |
| SG004 | core | high | a task id is reused |
| SG007 | core | high | a task carries `[US9]` but `spec.md` has fewer than nine user stories |
| SG008 | core | medium | a user story has no task labelled `[USn]` and no phase of its own |
| SG009 | core | high | an unresolved `[NEEDS CLARIFICATION]` survived into an artifact |
| SG010 | core | high | a task marked `[x]` names files that do not exist at HEAD |
| SG011 | core | medium | `plan.md` cites a requirement id that `spec.md` never mentions |
| SG012 | core | low | a success criterion is not mentioned in `tasks.md` (often expected for outcome KPIs) |
| SG013 | core | low | `spec.md` has requirement ids but none in a layout the parser recognises |
| SG006 | strict | medium | a checklist line has no `T###` id |
| SG101 | strict | medium | a task inside a user-story phase has no `[USn]` label |
| SG102 | strict | low | a task outside a user-story phase carries a `[USn]` label |
| SG103 | strict | low | a task names no file path |
| SG104 | strict | medium | `tasks.md` has tasks but no phase headings |
| SG105 | strict | medium | a user story has no Given/When/Then scenario |
| SG106 | strict | low | a user story has no "Why this priority" / "Independent Test" |
| SG107 | strict | low | placeholder text (`TKTK`, `TBD`, `???`) is left in an artifact |

`core` rules are always on: they describe something *wrong*, not something
*stylistically different*. `strict` rules encode the shipped template and are
opt-in, because mature repositories legitimately diverge from it.

## Coverage without guessing

`/analyze` maps tasks to requirements "by keyword / explicit reference
patterns". Keyword inference is not reproducible, so the gate only counts text
that is actually present, and it says which channel it used:

* `explicit` — a task line cites the id (`- [ ] T012 … (FR-003)`).
* `mention` — the id appears in `tasks.md` somewhere else: a phase heading
  (`### T024b — Authorization check (FR-010 …)`), a traceability table, a note.
* `none` — the id appears nowhere.

Counting mentions as coverage is the measured choice: it removed 112 of 545
uncovered-requirement findings on the corpus, because those ids *are* accounted
for — just not on a checkbox line. Use `--coverage-mode explicit` when you want
the stricter definition.

When an artifact set carries no links at all, the report says
`coverage: null` plus a reason instead of printing a confident `0 %` (or a fake
`100 %`). A tool that cannot see a relationship should not invent one.

## Measurements

Everything below was produced on this repository's `gate` module on
2026-10-29, on Windows, Python 3.13.

**Corpus.** 274 real feature directories (`spec.md` + `plan.md` + `tasks.md`)
harvested from public GitHub repositories via code search — 6 691 requirement
declarations, 10 281 task lines, 925 user stories. The corpus lives outside the
repository; the harvest script searched `filename:tasks.md "FR-001"` and kept
every directory that contained all three artifacts.

| Metric | Value |
|---|---|
| feature directories | 274 |
| requirement declarations parsed | 6 691 |
| task lines parsed | 10 281 |
| user stories parsed | 925 |
| sets where coverage is decidable | 255 / 274 |
| median requirement coverage | 76.19 % |
| median share of tasks citing an id | 38.9 % |
| sets with no high/critical finding | 102 / 274 |

Findings on that corpus (core rules only):

| Rule | Findings |
|---|---|
| SG003 uncovered requirement | 1 285 |
| SG012 success criterion not reflected | 747 |
| SG004 duplicate task id | 54 |
| SG008 story without tasks | 51 |
| SG009 unresolved clarification | 22 |
| SG013 unparseable layout (reported, not silent) | 15 |
| SG007 dangling story label | 7 |
| SG011 plan cites unknown requirement | 4 |
| SG001 duplicate requirement | 0 |
| SG002 dangling task reference | 0 |

**Self-audit.** Every reference-based finding was re-checked against the raw
text: SG003 only fires when the id is absent from `tasks.md`, SG002 only when
the id is absent from `spec.md`. Contradictions: **0 of 2 185**.

**Mutation.** One defect was injected at a time into 53–60 real artifact sets
per rule class; detection means the target rule reported the injected subject,
collateral means some other finding appeared that was not there before.

| Mutation | Cases | Hit | Miss |
|---|---|---|---|
| dangling task reference | 53 | 53 | 0 |
| duplicate task id | 53 | 51 | 2 |
| dangling story label | 53 | 41 | 12 |
| uncovered requirement | 53 | 53 | 0 |
| unresolved clarification | 53 | 53 | 0 |
| completed task, file absent | 53 | 51 | 2 |
| plan references unknown requirement | 60 | 53 | 7 |
| duplicate requirement | 53 | 53 | 0 |
| **total** | **431** | **408 (94.7 %)** | **23** |

The 23 misses are inputs that cannot be judged, not defects that were missed:
13 sets have no user-story section at all (so `[US9]` is unverifiable) and 7 have
no requirement section the parser recognises (so a plan reference has nothing to
be checked against). Collateral findings: 4, all of them the same structural
change being reported by a neighbouring rule (e.g. a story losing its task also
loses its phase).

**What the corpus changed.** Each of these was a false positive found by running
against real repositories, not by reasoning about the code:

| Symptom | Cause | Fix |
|---|---|---|
| 161 phantom dangling references | `- **FR-001** Read-only.` counted as a reference because the text after the id did not start with `:` | declarations are positional (bullet / table / heading / bold paragraph) |
| 83 phantom duplicate requirements | sub-ids `FR-096a`, `FR-016b` truncated to their parent | ids keep a lower-case suffix |
| 57 phantom ordering findings | a "repair cycle" phase spliced between T088 and T026 — legitimate | ordering reported as a *metric*, not a finding |
| 112 phantom uncovered requirements | the id was in a phase heading, not on a task line | `mention` channel |
| 17 phantom duplicates after the fix | `T001-T004 — All complete` is a task *range* | ranges are not ids |
| 45 % of SG001 cases | one requirement split over `Component.` / `Behaviour.` bullets | duplicate requires textual similarity |
| 80 % of SG002 cases | references to a *sibling* feature's requirement | repo-wide id set |
| 3 phantom findings per run | `.claude/templates/spec.md` is a template, not a feature | dot-directories are pruned |

## Baseline: accept today, fail on tomorrow

A deterministic checker is still noisy on a mature repository (1 285 uncovered
requirements above are real, but nobody fixes them in one commit). Record them
once and fail only on new ones:

```bash
specify gate --baseline .specify/gate-baseline.json --update-baseline
specify gate --baseline .specify/gate-baseline.json
```

Fingerprints are built from the rule, the artifact, the subject and the message —
never the line number, so inserting a paragraph above a defect does not turn an
accepted finding into a "new" one.

```yaml
- name: Spec gate
  run: |
    pip install specify-cli
    specify gate --baseline .specify/gate-baseline.json
```

## Limitations

* **Layouts.** The parser recognises the layouts measured in the corpus
  (bullets, bold paragraphs, headings, prefixed ids, sub-ids). A spec that
  declares requirements only inside tables or inside custom prose is reported as
  such (SG013) instead of being judged.
* **Paths.** SG010 compares the declared path with the working tree at HEAD. A
  file that was moved after the task was written counts as absent.
* **Semantics.** The gate does not judge whether a requirement is *good*, whether
  two requirements contradict each other, or whether a task is well scoped. That
  is what the LLM pass is for; this tool covers the part where "same input,
  same answer" is achievable.
* **Windows.** Path checks are case-insensitive there because the filesystem is.

## License

MIT, inherited from Spec Kit. This module is an addition to the upstream
repository; the upstream sources are unmodified except for one registration line
in `src/specify_cli/__init__.py`.
