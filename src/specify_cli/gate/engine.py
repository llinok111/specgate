"""Discovery, evaluation and report assembly."""

from __future__ import annotations

import os
from pathlib import Path

from .coverage import build_coverage
from .model import ArtifactSet, Report
from .parse import find_ids, parse_requirements, parse_stories, parse_tasks
from .rules import run_rules

GATE_VERSION = "1.0.0"

PRUNE = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "site-packages",
}

SKIP_SUFFIXES = (".venv", ".egg-info")


def discover(root: Path, max_depth: int = 6) -> list[Path]:
    """Find feature directories: a directory holding both spec.md and tasks.md.

    Dot-directories are pruned: ``.claude/templates``, ``.cursor`` and friends
    contain *copies of the templates*, which parse cleanly but describe no
    feature (measured: they produced three phantom findings on the first real
    corpus run).
    """
    found: list[Path] = []
    root = root.resolve()
    if (root / "tasks.md").is_file() and (root / "spec.md").is_file():
        found.append(root)
        return found

    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in PRUNE
            and not d.startswith(".")
            and not d.endswith(SKIP_SUFFIXES)
        )
        if depth >= max_depth:
            dirnames[:] = []
        if "tasks.md" in filenames and "spec.md" in filenames:
            found.append(Path(dirpath))
            dirnames[:] = []
    return sorted(found)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


_ROOT_IDS_CACHE: dict[str, dict[str, frozenset[str]]] = {}


def _ids_by_feature(root: Path) -> dict[str, frozenset[str]]:
    """Requirement ids declared per feature, computed once per repository.

    The first implementation recomputed this for every feature — O(features²)
    file reads, which turned a 270-feature corpus into a two-minute run.
    """
    key = str(root.resolve())
    cached = _ROOT_IDS_CACHE.get(key)
    if cached is not None:
        return cached
    table: dict[str, frozenset[str]] = {}
    for feature in discover(root.resolve()):
        table[str(feature.resolve())] = frozenset(find_ids(_read(feature / "spec.md")))
    _ROOT_IDS_CACHE[key] = table
    return table


def sibling_ids(root: Path, directory: Path) -> frozenset[str]:
    """Requirement ids declared by *other* features of the same repo.

    Multi-feature repositories routinely reference a sibling feature's
    requirement (``007 FR-041``). Without this set, every such reference is
    reported as dangling — 57 of 71 corpus findings.
    """
    own = str(directory.resolve())
    ids: set[str] = set()
    for feature, feature_ids in _ids_by_feature(root).items():
        if feature != own:
            ids.update(feature_ids)
    return frozenset(ids)


def load(directory: Path, root: Path) -> ArtifactSet:
    spec_path = directory / "spec.md"
    plan_path = directory / "plan.md"
    tasks_path = directory / "tasks.md"
    constitution_path = root / ".specify" / "memory" / "constitution.md"
    if not constitution_path.is_file():
        constitution_path = root / "memory" / "constitution.md"

    a = ArtifactSet(
        root=str(root.resolve()),
        directory=_rel(directory, root) if directory.resolve() != root else "",
        spec=_read(spec_path),
        plan=_read(plan_path),
        tasks=_read(tasks_path),
        spec_path=_rel(spec_path, root),
        plan_path=_rel(plan_path, root),
        tasks_path=_rel(tasks_path, root),
        sibling_ids=sibling_ids(root, directory),
    )
    if constitution_path.is_file():
        a.constitution = _read(constitution_path)
        a.constitution_path = _rel(constitution_path, root)

    a.spec_id_count = len(set(find_ids(a.spec)))
    a.requirements = parse_requirements(a.spec, a.spec_path)
    a.stories = parse_stories(a.spec)
    a.task_items = parse_tasks(a.tasks)
    return a


def evaluate(
    directory: Path,
    root: Path,
    *,
    strict: bool = False,
    check_paths: bool = True,
    coverage_mode: str = "mention",
) -> Report:
    a = load(directory, root)
    rows, metrics = build_coverage(a)
    a.coverage_rows = rows
    findings = run_rules(
        a,
        strict=strict,
        coverage_encodable=bool(metrics["coverage_encodable"]),
        coverage_mode=coverage_mode,
    )
    metrics["coverage_mode"] = coverage_mode
    if not check_paths:
        findings = [f for f in findings if f.rule != "SG010"]
        metrics["paths_checked"] = False
    a.findings = findings
    return Report(
        version=GATE_VERSION,
        directory=a.directory or ".",
        files={"spec": a.spec_path, "plan": a.plan_path, "tasks": a.tasks_path},
        findings=findings,
        coverage=rows,
        metrics=metrics,
    )
