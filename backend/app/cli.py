"""CLI sin servidor/base: mismos parser y motor que HTTP; errores a stderr, informe a stdout."""

import argparse
import json
import sys
from pathlib import Path

from app.adapters.oasdiff import OasdiffEngine
from app.core.config import Settings
from app.domain.models import GuardError
from app.services.comparisons import summarize
from app.services.specifications import parse_specification


def main() -> int:
    """Codigos estables para CI: 0 compatible, 1 breaking, 2 validacion/ejecucion."""
    parser = argparse.ArgumentParser(prog="contract-guard")
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("compare", help="Compare two local OpenAPI contracts")
    compare.add_argument("--base", required=True, type=Path)
    compare.add_argument("--target", required=True, type=Path)
    compare.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    settings = Settings()
    try:
        specs = []
        for path in [args.base, args.target]:
            with path.open("rb") as stream:
                specs.append(
                    parse_specification(
                        stream.read(settings.max_upload_bytes + 1),
                        path.name,
                        settings.max_upload_bytes,
                    )
                )
        engine = OasdiffEngine(settings.oasdiff_path, settings.comparison_timeout)
        findings = engine.compare(specs[0].document, specs[1].document)
        result, summary = summarize(findings)
        report = {
            "overall_result": result,
            "summary": summary,
            "baseline_hash": specs[0].content_hash,
            "candidate_hash": specs[1].content_hash,
            "engine": {
                "name": "oasdiff",
                "version": engine.version,
                "configuration": engine.configuration,
            },
            "findings": [finding.to_dict() for finding in findings],
        }
        if args.format == "json":
            print(json.dumps(report, indent=2))
        else:
            print(f"{result.upper()}: {summary['total']} changes; {summary['breaking']} breaking")
            for finding in findings:
                print(
                    f"[{finding.severity}] {finding.location}: {finding.description} ({finding.rule_id})"
                )
        return 1 if summary["breaking"] else 0
    except (GuardError, OSError) as exc:
        print(
            json.dumps(
                {"error": {"code": getattr(exc, "code", "file_error"), "message": str(exc)}}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
