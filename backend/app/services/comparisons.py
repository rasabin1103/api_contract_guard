"""Resumen de hallazgos compartido por API y CLI; no consulta HTTP ni SQL."""

from collections import Counter

from app.domain.models import Finding


def summarize(findings: list[Finding]) -> tuple[str, dict[str, int]]:
    """Compatible significa sin reglas breaking/advertencia, no documentos identicos."""
    counts = Counter(finding.severity for finding in findings)
    summary = {
        key: counts[key]
        for key in ("breaking", "potentially_breaking", "non_breaking", "informational")
    }
    summary["total"] = len(findings)
    if summary["breaking"]:
        result = "breaking"
    elif summary["potentially_breaking"]:
        result = "review_required"
    else:
        result = "compatible"
    return result, summary
