"""CLI adapter for ``specify gate``."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from .gate import baseline as _baseline
from .gate.engine import discover, evaluate
from .gate.render import to_json, to_sarif, to_text

SEVERITIES = ("critical", "high", "medium", "low")
FORMATS = ("text", "json", "sarif")


def _fail_threshold(value: str) -> int:
    if value == "never":
        return -1
    if value not in SEVERITIES:
        raise typer.BadParameter(f"expected one of {', '.join(SEVERITIES)} or 'never'")
    return SEVERITIES.index(value)


def _emit(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _fail_index(counts: dict[str, int], threshold: int) -> bool:
    if threshold < 0:
        return False
    return any(counts[sev] for sev in SEVERITIES[: threshold + 1])


def check(
    paths: list[Path] = typer.Argument(
        None,
        help="Project or directory to scan. Defaults to the current directory; "
        "every directory holding spec.md + tasks.md is treated as a feature.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Also enforce the checklist format the templates require (noisier).",
    ),
    fmt: str = typer.Option(
        "text", "--format", "-f", help="Output format: text, json or sarif."
    ),
    fail_on: str = typer.Option(
        "high",
        "--fail-on",
        help="Lowest severity that makes the command exit 1, or 'never'.",
    ),
    baseline: Path | None = typer.Option(
        None, "--baseline", help="Only fail on findings this baseline does not contain."
    ),
    update_baseline: bool = typer.Option(
        False,
        "--update-baseline",
        help="Rewrite the baseline from the current findings.",
    ),
    check_paths: bool = typer.Option(
        True,
        "--check-paths/--no-check-paths",
        help="Verify that files named by completed tasks exist (SG010).",
    ),
    coverage_mode: str = typer.Option(
        "mention",
        "--coverage-mode",
        help="What counts as coverage: 'mention' (id appears anywhere in tasks.md) "
        "or 'explicit' (a task line cites it).",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="How many findings to print in text mode."
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Print nothing on success."
    ),
) -> None:
    """Check spec.md / plan.md / tasks.md for mechanical inconsistencies.

    Exit codes: 0 clean, 1 findings at or above --fail-on, 2 usage or I/O error,
    3 unusable baseline.
    """
    if fmt not in FORMATS:
        raise typer.BadParameter(f"expected one of {', '.join(FORMATS)}")
    if coverage_mode not in ("mention", "explicit"):
        raise typer.BadParameter("expected 'mention' or 'explicit'")
    if update_baseline and baseline is None:
        typer.secho(
            "specify gate: --update-baseline requires --baseline PATH", err=True
        )
        raise typer.Exit(2)

    threshold = _fail_threshold(fail_on)
    roots = list(paths) if paths else [Path.cwd()]
    for root in roots:
        if not root.exists():
            typer.secho(f"specify gate: path does not exist: {root}", err=True)
            raise typer.Exit(2)

    reports = []
    for root in roots:
        root_path = root.resolve()
        directories = discover(root_path)
        if not directories:
            if fmt == "text" and not quiet:
                typer.secho(
                    f"specify gate: no feature directory (spec.md + tasks.md) under {root}",
                    err=True,
                )
            continue
        for directory in directories:
            reports.append(
                evaluate(
                    directory,
                    root_path,
                    strict=strict,
                    check_paths=check_paths,
                    coverage_mode=coverage_mode,
                )
            )

    if not reports:
        raise typer.Exit(0)

    accepted: set[str] | None = None
    if baseline is not None:
        if update_baseline and not baseline.exists():
            # First run of `--update-baseline` creates the file from scratch.
            accepted = set()
        else:
            try:
                accepted = _baseline.read(baseline)
            except _baseline.BaselineError as exc:
                typer.secho(f"specify gate: {exc}", err=True)
                raise typer.Exit(3) from exc

    if update_baseline and accepted is not None:
        every = [f for report in reports for f in report.findings]
        _baseline.write(baseline, every)  # type: ignore[arg-type]
        if fmt == "text" and not quiet:
            typer.echo(
                f"baseline written: {baseline} "
                f"({len({f.fingerprint() for f in every})} accepted)"
            )
        # Recording a baseline is an accept action: the run passes by definition.
        raise typer.Exit(0)

    exit_code = 0
    for report in reports:
        if accepted is not None:
            new, fixed = _baseline.diff(report.findings, accepted)
            report.findings = new
            if fmt == "text" and not quiet:
                typer.echo(
                    f"baseline: {len(accepted)} accepted, {len(new)} new, {fixed} fixed"
                )

        if fmt == "json":
            _emit(to_json(report, strict=strict))
        elif fmt == "sarif":
            _emit(to_sarif(report, strict=strict))
        elif not quiet or report.findings:
            _emit(to_text(report, strict=strict, max_findings=max_findings))

        if _fail_index(report.counts(), threshold):
            exit_code = 1

    raise typer.Exit(exit_code)


gate_app = typer.Typer(
    name="gate",
    help="Deterministic conformance checks for spec artifacts.",
    add_completion=False,
)
gate_app.command(name="check")(check)


def register(app: typer.Typer) -> None:
    """Register ``specify gate`` on the root application.

    Registered as a *group* (like ``specify self`` or ``specify extension``)
    rather than a root command: the root command list is part of the public CLI
    surface and is asserted by the upstream test suite.
    """
    app.add_typer(gate_app, name="gate")
