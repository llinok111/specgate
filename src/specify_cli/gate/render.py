"""Rendering: plain text (byte-stable), JSON, SARIF.

Text output deliberately avoids ``rich``: a gate that is used as a CI baseline
must emit the same bytes on every machine and terminal width.
"""

from __future__ import annotations

import json

from .model import Report

SEV_ORDER = ("critical", "high", "medium", "low")


def to_dict(report: Report, *, strict: bool) -> dict:
    counts = report.counts()
    return {
        "gate": "specgate",
        "gate_version": report.version,
        "strict": strict,
        "directory": report.directory,
        "files": report.files,
        "counts": {k: counts[k] for k in SEV_ORDER},
        "total": len(report.findings),
        "metrics": report.metrics,
        "coverage": [
            {
                "id": c.rid,
                "kind": c.kind,
                "line": c.line,
                "tasks": list(c.tasks),
                "channel": c.channel,
                "text": c.text,
            }
            for c in report.coverage
        ],
        "findings": [
            {
                "rule": f.rule,
                "severity": f.severity,
                "tier": f.tier,
                "artifact": f.artifact,
                "line": f.line,
                "subject": f.subject,
                "message": f.message,
                "fingerprint": f.fingerprint(),
                "detail": dict(sorted(f.detail.items())),
            }
            for f in report.findings
        ],
    }


def to_json(report: Report, *, strict: bool) -> str:
    return (
        json.dumps(
            to_dict(report, strict=strict),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def to_text(report: Report, *, strict: bool, max_findings: int = 200) -> str:
    lines: list[str] = []
    counts = report.counts()
    m = report.metrics

    cov = m.get("coverage_pct")
    cov_txt = "n/a (not encodable)" if cov is None else f"{cov}%"
    lines.append(f"specgate {report.version}  {report.directory}")
    lines.append(
        f"  requirements={m.get('requirements')}  tasks={m.get('tasks')}  "
        f"stories={m.get('stories')}  coverage={cov_txt}"
    )
    lines.append(
        "  findings: "
        + "  ".join(f"{k}={counts[k]}" for k in SEV_ORDER)
        + f"  total={len(report.findings)}"
    )
    if not m.get("coverage_encodable") and m.get("requirements"):
        lines.append(f"  note: {m.get('coverage_reason')}")

    if report.findings:
        lines.append("")
        shown = report.findings[:max_findings]
        width = max(len(f.artifact) for f in shown)
        for f in shown:
            loc = f"{f.artifact}:{f.line}" if f.line else f.artifact
            lines.append(
                f"  {f.severity.upper():<8} {f.rule}  {loc:<{width + 6}}  {f.message}"
            )
        if len(report.findings) > len(shown):
            lines.append(
                f"  ... {len(report.findings) - len(shown)} more findings (use --json)"
            )
    else:
        lines.append("")
        lines.append("  no findings")

    return "\n".join(lines) + "\n"


def to_sarif(report: Report, *, strict: bool) -> str:
    rules = {}
    results = []
    level = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}
    for f in report.findings:
        rules.setdefault(
            f.rule,
            {
                "id": f.rule,
                "name": f.rule,
                "shortDescription": {"text": f.message},
                "properties": {"tier": f.tier, "severity": f.severity},
            },
        )
        results.append(
            {
                "ruleId": f.rule,
                "level": level[f.severity],
                "message": {"text": f.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.artifact},
                            "region": {"startLine": f.line or 1},
                        }
                    }
                ],
                "partialFingerprints": {"specgate": f.fingerprint()},
            }
        )
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "specgate",
                        "version": report.version,
                        "rules": [rules[k] for k in sorted(rules)],
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
