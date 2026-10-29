"""specgate — a deterministic conformance gate for Spec Kit artifacts.

Spec Kit's ``/analyze`` and ``/converge`` commands ask a language model to find
inconsistencies between ``spec.md``, ``plan.md`` and ``tasks.md``. The prompt is
good, the output is not reproducible: the same commit can be green on Monday and
red on Tuesday, which makes the command unusable as a CI gate (see upstream
issues #543 and #3752).

This package implements the *mechanical* half of that analysis — the part with
an unambiguous answer — as a deterministic checker with a stable exit code:

* identifiers: duplicates, gaps, out-of-order task ids, dangling references
* coverage: requirement → task, refusing to guess when the link is absent
* stories: labels that point at a story which does not exist, stories with no
  task, stories with no acceptance scenario
* completion: a task marked ``[x]`` whose declared file never appeared
* format (opt-in, ``--strict``): the checklist format the template requires

See ``README.md`` in this directory for the rule table and the measured
false-positive rate on real repositories.
"""

from __future__ import annotations

from .engine import GATE_VERSION, discover, evaluate, load
from .model import ArtifactSet, Finding, Report, RequirementCoverage

__all__ = [
    "GATE_VERSION",
    "ArtifactSet",
    "Finding",
    "Report",
    "RequirementCoverage",
    "discover",
    "evaluate",
    "load",
]
