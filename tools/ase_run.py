"""Ejecuta Contract Guard para ASE (workflow_dispatch) o en local.

Usa directamente el motor del repo (sin servidor ni base de datos), igual que
backend/app/cli.py, y escribe:
  - report.html          informe autocontenido (artefacto "pytest-report")
  - request_result.json  resultado en bruto (artefacto "request-result")

Entradas por variables de entorno CG_* (las rellena el workflow):
  CG_MODE          compare | validate_contract | validate_schema
  CG_CONTRACT_A    compare: referencia. validate_contract: contrato a usar
  CG_CONTRACT_B    compare: candidato
  CG_SCHEMA        validate_schema: JSON Schema
  CG_RESPONSE      validate_contract / validate_schema: respuesta JSON
  CG_PATH, CG_METHOD, CG_STATUS_CODE   validate_contract
Cada archivo puede ser: un adjunto de ASE (gz64:<nombre>:<base64 gzip>), una URL
https o una ruta relativa dentro del repo.

Salida: 0 conforme · 1 cambios incompatibles / respuesta no conforme · 2 error.
Uso local (desde la raiz del repo, con backend instalado y oasdiff disponible):
  CG_MODE=compare CG_CONTRACT_A=examples/openapi-v1.yaml \
  CG_CONTRACT_B=examples/openapi-v2-breaking.yaml python tools/ase_run.py
"""

from __future__ import annotations

import base64
import binascii
import gzip
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.adapters.oasdiff import OasdiffEngine  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.domain.models import GuardError  # noqa: E402
from app.services.comparisons import summarize  # noqa: E402
from app.services.response_validation import (  # noqa: E402
    parse_json_file,
    validate_json_schema,
    validate_openapi_response,
)
from app.services.specifications import parse_specification  # noqa: E402

SETTINGS = Settings()
MAX_BYTES = SETTINGS.max_upload_bytes


KEYWORDS = {
    "type", "properties", "required", "items", "enum", "const", "$ref", "allOf", "anyOf", "oneOf",
    "not", "if", "then", "else", "format", "pattern", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems", "uniqueItems",
    "additionalProperties", "patternProperties", "prefixItems", "contains", "$defs", "definitions",
    "multipleOf", "minProperties", "maxProperties", "dependentRequired", "propertyNames",
}


def env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


# --- informe -----------------------------------------------------------------

STYLE = (
    "body{font-family:system-ui,sans-serif;margin:2rem;color:#111}h1{font-size:1.4rem}"
    "table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border:1px solid #ccc;padding:.4rem .6rem;"
    "text-align:left;vertical-align:top;font-size:.9rem}th{background:#f3f4f6}.pill{padding:.15rem .5rem;"
    "border-radius:999px;font-weight:600;font-size:.8rem}.bad{background:#fee2e2;color:#991b1b}"
    ".warn{background:#fef3c7;color:#92400e}.ok{background:#dcfce7;color:#166534}.muted{color:#6b7280}"
    "pre{background:#f3f4f6;padding:.6rem;overflow:auto;font-size:.8rem}"
)
SEVERITY_CLASS = {"breaking": "bad", "potentially_breaking": "warn", "non_breaking": "ok", "informational": "muted"}


def pill(text: str, cls: str) -> str:
    return f"<span class='pill {cls}'>{html.escape(text)}</span>"


def write_report(title: str, data: dict, body_html: str = "") -> None:
    Path("request_result.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    fallback = "<pre>" + html.escape(json.dumps(data, indent=2, ensure_ascii=False)) + "</pre>"
    Path("report.html").write_text(
        f"<!doctype html><html lang='es'><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"<style>{STYLE}</style><h1>{html.escape(title)}</h1>{body_html or fallback}",
        encoding="utf-8",
    )


HINTS = {
    "missing_input": "Rellena todas las entradas obligatorias del modo elegido.",
    "invalid_attachment": "Vuelve a adjuntar el archivo (.json, .yaml o .yml).",
    "download_failed": "Comprueba que la URL https es publica y accesible.",
    "invalid_source": "Usa un adjunto, una URL https o una ruta relativa del repo.",
    "file_not_found": "Revisa la ruta dentro del repo.",
    "upload_too_large": "Reduce el archivo (maximo 2 MiB).",
    "invalid_schema": "Pasa el JSON Schema directamente (el objeto con type/properties), sin envoltorios.",
    "unknown_mode": "Elige compare, validate_contract o validate_schema.",
}


def ase_block(mode, verdict, headline, explanation="", metrics=(), findings=(), inputs=(), truncated=False) -> dict:
    """Bloque legible que ASE muestra como tarjeta de resultado."""
    return {
        "tool": "API Contract Guard",
        "mode": mode,
        "verdict": verdict,  # pass | warn | fail | error
        "headline": headline,
        "explanation": explanation,
        "metrics": [{"label": a, "value": str(b), "tone": c} for a, b, c in metrics],
        "findings": list(findings),
        "inputs": [{"label": a, "value": str(b)} for a, b in inputs],
        "truncated": truncated,
    }


def fail(message: str, code: str = "error") -> None:
    data = {
        "error": {"code": code, "message": message},
        "ase_result": ase_block(
            env("CG_MODE") or "compare",
            "error",
            "La ejecucion no se pudo completar",
            message,
            findings=[{"severity": "error", "title": code, "detail": message, "hint": HINTS.get(code, "")}],
        ),
    }
    write_report("Contract Guard · Error", data)
    print(f"ERROR [{code}]: {message}", file=sys.stderr)
    sys.exit(2)


# --- entradas ----------------------------------------------------------------


def load(source: str, label: str) -> tuple[str, bytes]:
    """Lee un adjunto de ASE (gz64:), una URL https o una ruta del repo (max 2 MiB)."""
    if not source:
        fail(f"Falta la entrada '{label}'.", "missing_input")
    if source.startswith("gz64:"):
        try:
            _, quoted_name, packed = source.split(":", 2)
            data = gzip.decompress(base64.b64decode(packed))
        except (ValueError, OSError, binascii.Error):
            fail(f"El archivo adjunto de '{label}' no es valido.", "invalid_attachment")
        name = urllib.parse.unquote(quoted_name) or label
    elif source.startswith("https://"):
        try:
            with urllib.request.urlopen(source, timeout=30) as resp:  # noqa: S310
                data = resp.read(MAX_BYTES + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            fail(f"No se pudo descargar '{label}': {exc}", "download_failed")
        name = source.rsplit("/", 1)[-1].split("?", 1)[0] or label
    elif source.startswith(("http://", "file:", "/", "..")) or ".." in Path(source).parts:
        fail(f"'{label}' debe ser un adjunto, una URL https o una ruta relativa del repo.", "invalid_source")
    else:
        path = Path(source)
        if not path.is_file():
            fail(f"'{label}': no existe el archivo {source} en el repo.", "file_not_found")
        data = path.read_bytes()[: MAX_BYTES + 1]
        name = path.name
    if len(data) > MAX_BYTES:
        fail(f"'{label}' supera {MAX_BYTES // (1024 * 1024)} MiB.", "upload_too_large")
    return name, data


# --- modos -------------------------------------------------------------------


def run_compare() -> int:
    name_a, raw_a = load(env("CG_CONTRACT_A"), "contract_a")
    name_b, raw_b = load(env("CG_CONTRACT_B"), "contract_b")
    base = parse_specification(raw_a, name_a, MAX_BYTES)
    target = parse_specification(raw_b, name_b, MAX_BYTES)
    engine = OasdiffEngine(SETTINGS.oasdiff_path, SETTINGS.comparison_timeout)
    all_findings = engine.compare(base.document, target.document)
    # Por defecto se informa de TODO lo estructural (operaciones, parametros, campos
    # de la respuesta y sus tipos, y `servers`). CG_SCOPE=structure omite `servers`.
    scope = (env("CG_SCOPE") or "all").lower()
    ignored = [f for f in all_findings if f.category == "servers"] if scope == "structure" else []
    findings = [f for f in all_findings if f not in ignored]
    result, summary = summarize(findings)
    report = {
        "overall_result": result,
        "summary": summary,
        "baseline": {"file": name_a, "content_hash": base.content_hash},
        "candidate": {"file": name_b, "content_hash": target.content_hash},
        "engine": {"name": "oasdiff", "version": engine.version, "configuration": engine.configuration},
        "scope": scope,
        "ignored_findings": len(ignored),
        "findings": [f.to_dict() for f in findings],
    }
    verdict = {"breaking": "fail", "review_required": "warn", "compatible": "pass"}.get(str(result), "warn")
    headline = {
        "breaking": "Cambios incompatibles: la version candidata rompe a los consumidores actuales",
        "review_required": "Hay cambios que conviene revisar antes de publicar",
        "compatible": "Compatible: no se detectan cambios que rompan a los consumidores",
    }.get(str(result), str(result))
    sev_tone = {"breaking": "error", "potentially_breaking": "warning", "non_breaking": "success"}
    report["ase_result"] = ase_block(
        "compare",
        verdict,
        headline,
        "Se comparan la estructura y los tipos de los campos de peticion/respuesta, no los textos ni los valores de ejemplo. Compatible no garantiza el comportamiento del servidor."
        + (f" Se omitieron {len(ignored)} cambio(s) de configuracion de servidores (URLs base)." if ignored else ""),
        metrics=[(k.replace("_", " "), v, sev_tone.get(k, "")) for k, v in summary.items() if isinstance(v, (int, str))],
        findings=[
            {
                "severity": str(f.severity),
                "title": f.description,
                "location": f"{ {'response': 'respuesta', 'request': 'peticion', 'operation': 'operacion'}.get(f.category, f.category) } · {f.location}",
                "detail": f.rule_id,
                "hint": f.recommendation or "",
            }
            for f in findings
        ],
        inputs=[("Referencia", name_a), ("Candidata", name_b), ("Motor", f"oasdiff {engine.version}")],
    )
    cls = {"breaking": "bad", "review_required": "warn", "compatible": "ok"}.get(str(result), "muted")
    rows = "".join(
        f"<tr><td>{pill(str(f.severity), SEVERITY_CLASS.get(f.severity, 'muted'))}</td>"
        f"<td>{html.escape(f.category)}</td><td>{html.escape(f.location)}</td>"
        f"<td>{html.escape(f.description)}<br><span class='muted'>{html.escape(f.rule_id)}</span></td>"
        f"<td>{html.escape(f.recommendation or '')}</td></tr>"
        for f in findings
    )
    table = (
        "<table><tr><th>Severidad</th><th>Categoria</th><th>Ubicacion</th><th>Detalle</th>"
        f"<th>Recomendacion</th></tr>{rows}</table>"
        if rows
        else "<p class='muted'>No se encontraron diferencias soportadas entre las dos versiones.</p>"
    )
    body = (
        f"<p>Resultado: {pill(str(result), cls)} · referencia <b>{html.escape(name_a)}</b> "
        f"→ candidata <b>{html.escape(name_b)}</b></p>"
        f"<pre>{html.escape(json.dumps(summary, indent=2, ensure_ascii=False))}</pre>{table}"
        "<p class='muted'>Compatible no garantiza que los documentos sean identicos ni el "
        f"comportamiento del servidor. Motor: oasdiff {html.escape(str(engine.version))}.</p>"
    )
    write_report("Contract Guard · Comparacion de contratos", report, body)
    return 1 if summary["breaking"] else 0


def render_validation(report: dict, title: str, mode: str = "validate") -> int:
    valid = bool(report.get("valid"))
    rows = "".join(
        f"<tr><td>{html.escape(str(e.get('path') or '(cuerpo)'))}</td><td>{html.escape(str(e.get('rule', '')))}</td>"
        f"<td>{html.escape(str(e.get('message', '')))}</td></tr>"
        for e in report.get("errors", [])
    )
    table = f"<table><tr><th>Donde</th><th>Regla</th><th>Detalle</th></tr>{rows}</table>" if rows else ""
    trunc = "<p class='muted'>Solo se muestran los primeros errores; hay mas.</p>" if report.get("truncated") else ""
    warnings = "".join(f"<li>{html.escape(str(w))}</li>" for w in report.get("warnings", []))
    errs = report.get("errors", [])
    report = {
        **report,
        "ase_result": ase_block(
            mode,
            "pass" if valid else "fail",
            "La respuesta cumple el esquema" if valid else f"La respuesta NO cumple ({len(errs)} error(es))",
            f"Alcance: {report.get('validation_scope', '')}" if report.get("validation_scope") else "",
            metrics=[("errores", len(errs), "success" if valid else "error"), ("avisos", len(report.get("warnings", [])), "warning")],
            findings=[
                {
                    "severity": "error",
                    "title": str(e.get("message", "")),
                    "location": str(e.get("path") or "(cuerpo)"),
                    "detail": f"Regla: {e.get('rule', '')}",
                    "hint": "Corrige ese campo en la respuesta o ajusta el contrato/esquema si el cambio es intencionado.",
                }
                for e in errs
            ]
            + [{"severity": "warning", "title": str(w)} for w in report.get("warnings", [])],
            inputs=[(k, report[k]) for k in ("contract_file",) if report.get(k)],
            truncated=bool(report.get("truncated")),
        ),
    }
    body = (
        f"<p>{pill('La respuesta cumple' if valid else 'La respuesta no cumple', 'ok' if valid else 'bad')}</p>"
        f"<p class='muted'>Alcance: {html.escape(str(report.get('validation_scope', '')))}</p>"
        f"{table}{trunc}{('<ul>' + warnings + '</ul>') if warnings else ''}"
    )
    write_report(title, report, body)
    return 0 if valid else 1


def parse_json(label: str, name: str, raw: bytes):
    return parse_json_file(raw, name if name.lower().endswith(".json") else name + ".json", MAX_BYTES)


def run_validate_contract() -> int:
    name_c, raw_c = load(env("CG_CONTRACT_A"), "contract_a")
    name_r, raw_r = load(env("CG_RESPONSE"), "response")
    spec = parse_specification(raw_c, name_c, MAX_BYTES)
    status_code = env("CG_STATUS_CODE") or "200"
    report = validate_openapi_response(
        spec.document,
        env("CG_PATH"),
        (env("CG_METHOD") or "GET").upper(),
        int(status_code) if status_code.isdigit() else status_code,
        "application/json",
        parse_json("response", name_r, raw_r),
        True,
        SETTINGS.comparison_timeout,
    )
    report = {**report, "contract_file": name_c, "content_hash": spec.content_hash}
    return render_validation(report, "Contract Guard · Validacion contra contrato", "validate_contract")


def run_validate_schema() -> int:
    name_s, raw_s = load(env("CG_SCHEMA"), "schema")
    name_r, raw_r = load(env("CG_RESPONSE"), "response")
    schema = parse_json("schema", name_s, raw_s)
    notes: list[str] = []
    # Error comun: envolver el esquema como {"schema": {...}}. Para JSON Schema, "schema"
    # no es una palabra clave, asi que se ignora y CUALQUIER respuesta pasaria por valida.
    if isinstance(schema, dict) and set(schema) == {"schema"} and isinstance(schema["schema"], dict):
        schema = schema["schema"]
        notes.append('El esquema venia envuelto en {"schema": ...}; se ha usado el contenido interno.')
    if not isinstance(schema, (dict, bool)) or (isinstance(schema, dict) and not (set(schema) & KEYWORDS)):
        fail(
            "El archivo de esquema no contiene ninguna palabra clave de JSON Schema "
            "(type, properties, required...). Con un esquema asi cualquier respuesta seria valida.",
            "invalid_schema",
        )
    report = validate_json_schema(schema, parse_json("response", name_r, raw_r), SETTINGS.comparison_timeout)
    report = {**report, "warnings": [*notes, *report.get("warnings", [])]}
    return render_validation(report, "Contract Guard · Validacion contra JSON Schema", "validate_schema")


MODES = {
    "compare": run_compare,
    "validate_contract": run_validate_contract,
    "validate_schema": run_validate_schema,
}


def main() -> int:
    mode = env("CG_MODE") or "compare"
    runner = MODES.get(mode)
    if runner is None:
        fail(f"Modo desconocido: {mode}", "unknown_mode")
    try:
        code = runner()
    except GuardError as exc:
        fail(exc.message, exc.code)
    except OSError as exc:
        fail(str(exc), "file_error")
    print("OK" if code == 0 else "El resultado no es conforme (ver report.html)")
    return code


if __name__ == "__main__":
    sys.exit(main())
