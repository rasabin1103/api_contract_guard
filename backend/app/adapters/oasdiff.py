"""Adaptador del motor externo: argumentos seguros, version fijada y hallazgos estables."""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.domain.models import Finding, GuardError

ENGINE_VERSION = "1.34.0"
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def _server_configuration(document: dict[str, Any]) -> dict[tuple[str, ...], Any]:
    """Inventario barato para decidir si hace falta ejecutar el diff suplementario.

    No clasifica cambios: el analisis sigue siendo de oasdiff. Se incluyen todos los
    scopes soportados y las rutas referenciadas tambien estan presentes en paths.
    """
    configuration: dict[tuple[str, ...], Any] = {(): document.get("servers")}
    for section in ("paths", "webhooks"):
        for path, item in document.get(section, {}).items():
            if "servers" in item:
                configuration[(section, path)] = item["servers"]
            for method in HTTP_METHODS.intersection(item):
                operation = item[method]
                if "servers" in operation:
                    configuration[(section, path, method)] = operation["servers"]
    return configuration


class OasdiffEngine:
    version = ENGINE_VERSION
    configuration: dict[str, Any] = {
        "command": "changelog",
        "supplemental_command": "diff",
        "adapter_version": "2",
        "supplemental_rules": {
            "acg-server-configuration-changed": {
                "routing": "potentially_breaking",
                "documentation_only": "informational",
            }
        },
        "level": "INFO",
        "allow_external_refs": False,
        "auto_upgrade": True,
        "severity_mapping": {
            "ERR": "breaking",
            "WARN": "potentially_breaking",
            "INFO": "non_breaking",
        },
    }

    def __init__(self, executable: str = "oasdiff", timeout: int = 30):
        self.executable, self.timeout = executable, timeout

    def _run(self, arguments: list[str], cwd: str) -> str:
        try:
            result = subprocess.run(
                [self.executable, *arguments],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GuardError("Comparison engine timed out", 504, "engine_timeout") from exc
        except OSError as exc:
            raise GuardError(
                "oasdiff is unavailable; install pinned version 1.34.0", 503, "engine_unavailable"
            ) from exc
        if result.returncode:
            raise GuardError(
                "Comparison engine could not process this specification", 422, "engine_error"
            )
        if len(result.stdout) > 16 * 1024 * 1024:
            raise GuardError("Comparison output exceeds limit", 422, "engine_output_limit")
        return result.stdout

    def compare(self, base: dict[str, Any], target: dict[str, Any]) -> list[Finding]:
        """Mantener el changelog completo; omitir solo un diff de servers innecesario."""
        with tempfile.TemporaryDirectory(prefix="contract-guard-") as directory:
            version = self._run(["--version"], directory)
            if version.strip() != f"oasdiff version {self.version}":
                raise GuardError(f"Expected oasdiff {self.version}", 503, "engine_version_mismatch")
            for name, document in [("base.json", base), ("target.json", target)]:
                Path(directory, name).write_text(json.dumps(document), encoding="utf-8")
            Path(directory, "config.yaml").write_text("{}", encoding="utf-8")
            output = self._run(
                [
                    "changelog",
                    "base.json",
                    "target.json",
                    "--format",
                    "json",
                    "--level",
                    "INFO",
                    "--allow-external-refs=false",
                    "--auto-upgrade",
                    "--config",
                    "config.yaml",
                ],
                directory,
            )
            differences = (
                self._run(
                    [
                        "diff",
                        "base.json",
                        "target.json",
                        "--format",
                        "json",
                        "--allow-external-refs=false",
                        "--auto-upgrade",
                        "--config",
                        "config.yaml",
                    ],
                    directory,
                )
                if _server_configuration(base) != _server_configuration(target)
                else "{}"
            )
        try:
            raw = json.loads(output) if output.strip() else []
            if raw is None:
                raw = []
            if not isinstance(raw, list):
                raise ValueError("Unexpected engine response")
            semantic_diff = json.loads(differences) if differences.strip() else {}
            if not isinstance(semantic_diff, dict):
                raise ValueError("Unexpected semantic diff response")
            findings = []
            for item in raw:
                rule = str(item["id"])
                level = item.get("level")
                severity = {
                    3: "breaking",
                    2: "potentially_breaking",
                    1: "non_breaking",
                    "ERR": "breaking",
                    "WARN": "potentially_breaking",
                    "INFO": "non_breaking",
                }.get(level, "informational")
                # Source locations contain temporary filenames; normalize them for stable exports.
                metadata = json.loads(
                    json.dumps(item).replace(directory.replace("\\", "\\\\"), "<input>")
                )
                stable = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
                if "response" in rule:
                    category = "response"
                elif "request" in rule:
                    category = "request"
                else:
                    category = "operation"
                path = str(item.get("path", ""))
                method = str(item.get("operation", "")).lower()
                # oasdiff's changelog supplies prose, not before/after scalar values.
                # Preserve the source operation as explicit context without parsing prose.
                previous = base.get("paths", {}).get(path, {}).get(method)
                current = target.get("paths", {}).get(path, {}).get(method)
                metadata["value_scope"] = "source_operation"
                findings.append(
                    Finding(
                        id=hashlib.sha256(stable.encode()).hexdigest()[:24],
                        rule_id=rule,
                        category=category,
                        severity=severity,
                        location=f"{item.get('operation', '')} {item.get('path', '')}".strip(),
                        description=str(item.get("text", rule)),
                        previous_value=previous,
                        current_value=current,
                        recommendation=(
                            "Preserve existing response guarantees; introduce changed output in a new major version."
                            if category == "response"
                            else "Continue accepting existing requests; make new inputs optional or version the operation."
                            if category == "request"
                            else "Retain the existing operation or deprecate it with a documented migration window."
                        ),
                        engine_metadata=metadata,
                    )
                )
            findings.extend(server_findings(semantic_diff, base, target))
            return sorted(
                findings, key=lambda finding: (finding.location, finding.rule_id, finding.id)
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise GuardError(
                "Invalid comparison engine response", 502, "engine_protocol_error"
            ) from exc


def server_findings(
    diff: dict[str, Any], base: dict[str, Any], target: dict[str, Any]
) -> list[Finding]:
    """Project server deltas from oasdiff's semantic diff, not text or prose parsing."""
    findings = []

    def append(delta: Any, location: str, previous: Any, current: Any) -> None:
        if not delta:
            return
        modifications = delta.get("modified", {})
        documentation_only = (
            bool(modifications)
            and not delta.get("added")
            and not delta.get("deleted")
            and all(set(change) <= {"description"} for change in modifications.values())
        )
        metadata = {
            "source": "oasdiff diff",
            "adapter_rule_id": "acg-server-configuration-changed",
            "value_scope": "servers",
            "semantic_diff": delta,
        }
        stable = json.dumps(
            {"location": location, "previous": previous, "current": current, "metadata": metadata},
            sort_keys=True,
            separators=(",", ":"),
        )
        findings.append(
            Finding(
                id=hashlib.sha256(stable.encode()).hexdigest()[:24],
                rule_id="acg-server-configuration-changed",
                category="servers",
                severity="informational" if documentation_only else "potentially_breaking",
                location=location,
                description=(
                    "Server documentation changed."
                    if documentation_only
                    else "Server configuration changed; clients may resolve a different API base URL."
                ),
                previous_value=previous,
                current_value=current,
                recommendation=(
                    "Review effective base URLs, inherited/default servers and generated client "
                    "configuration before release. This is an adapter review rule, not a confirmed breaking change."
                ),
                engine_metadata=metadata,
            )
        )

    append(diff.get("servers"), "/servers", base.get("servers"), target.get("servers"))
    for section in ("paths", "webhooks"):
        for path, path_diff in diff.get(section, {}).get("modified", {}).items():
            previous = base.get(section, {}).get(path, {})
            current = target.get(section, {}).get(path, {})
            pointer = f"/{section}/{path.replace('~', '~0').replace('/', '~1')}"
            append(
                path_diff.get("servers"),
                pointer + "/servers",
                previous.get("servers"),
                current.get("servers"),
            )
            for method, operation_diff in (
                path_diff.get("operations", {}).get("modified", {}).items()
            ):
                append(
                    operation_diff.get("servers"),
                    pointer + f"/{method.lower()}/servers",
                    previous.get(method.lower(), {}).get("servers"),
                    current.get(method.lower(), {}).get("servers"),
                )
    return findings
