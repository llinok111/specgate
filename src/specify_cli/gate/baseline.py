"""Baseline snapshots: accept today's findings, fail only on tomorrow's.

The reason this exists: ``/analyze`` is an LLM prompt, so re-running it on an
unchanged repository produces a different report each time (upstream issue
#543). A gate that flips between red and green for the same commit is useless
in CI. A baseline turns the gate into "no *new* defects", which is stable
because the underlying checks are deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Finding

BASELINE_VERSION = 1


def build(findings: list[Finding]) -> dict:
    prints = sorted({f.fingerprint() for f in findings})
    return {
        "gate": "specgate",
        "baseline_version": BASELINE_VERSION,
        "fingerprints": prints,
        "count": len(prints),
    }


def write(path: Path, findings: list[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build(findings), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


class BaselineError(RuntimeError):
    pass


def read(path: Path) -> set[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaselineError(f"cannot read baseline {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BaselineError(f"baseline {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("gate") != "specgate":
        raise BaselineError(f"baseline {path} was not written by specgate")
    prints = data.get("fingerprints")
    if not isinstance(prints, list):
        raise BaselineError(f"baseline {path} has no fingerprints list")
    return {str(p) for p in prints}


def diff(current: list[Finding], accepted: set[str]) -> tuple[list[Finding], int]:
    new = [f for f in current if f.fingerprint() not in accepted]
    fixed = len({f.fingerprint() for f in current} & accepted)
    return new, len(accepted) - fixed
