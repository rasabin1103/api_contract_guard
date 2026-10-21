"""Stateless validation of captured JSON responses; never calls the described API."""

import json
import multiprocessing
import re
from importlib.metadata import version
from itertools import islice
from threading import BoundedSemaphore
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from jsonschema.validators import extend
from openapi_schema_validator import OAS30ReadValidator, OAS31Validator
from referencing import Registry

from app.core.json_input import load_json
from app.domain.models import GuardError

MAX_ERRORS = 100
SLOTS = BoundedSemaphore(2)
DIALECTS = {
    "https://json-schema.org/draft/2020-12/schema",
    "https://spec.openapis.org/oas/3.1/dialect/base",
}
# En estos objetos las claves son nombres de campos/schemas, no keywords.
# Un campo llamado "$schema" debe conservarse y validarse como cualquier otro.
SCHEMA_MAP_KEYS = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas", "schemas"}
)


def bounded_json(value: Any, *, schema: bool = False) -> None:
    """Acotar el coste del recorrido y aplicar la politica local de referencias."""
    stack = [(value, 0, False)]
    count = 0
    while stack:
        current, depth, names_map = stack.pop()
        count += 1
        if count > 100_000 or depth > 64:
            raise GuardError("JSON exceeds structural complexity limits")
        if isinstance(current, dict):
            if schema and not names_map:
                if any(
                    key in current for key in ("$id", "$anchor", "$dynamicRef", "$dynamicAnchor")
                ):
                    raise GuardError(
                        "Schema identities, anchors and dynamic references are unsupported"
                    )
                ref = current.get("$ref")
                if ref is not None and (not isinstance(ref, str) or not ref.startswith("#/")):
                    raise GuardError("Only local #/ references are allowed")
                dialect = current.get("$schema")
                if dialect is not None and (
                    not isinstance(dialect, str) or dialect not in DIALECTS
                ):
                    raise GuardError(
                        "Only JSON Schema 2020-12 and the OpenAPI 3.1 dialect are supported"
                    )
            stack.extend(
                (item, depth + 1, key in SCHEMA_MAP_KEYS and not names_map)
                for key, item in current.items()
            )
        elif isinstance(current, list):
            stack.extend((item, depth + 1, False) for item in current)
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise GuardError("Only finite JSON values are allowed") from exc


def parse_json_file(content: bytes, filename: str, limit: int) -> Any:
    """Leer un fichero/JSON HTTP con los mismos limites y parser estricto."""
    if len(content) > limit:
        raise GuardError("JSON file exceeds size limit", 413, "upload_too_large")
    if not filename.lower().endswith(".json"):
        raise GuardError("Response validation accepts .json files only", 415, "unsupported_format")
    try:
        value = load_json(content)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise GuardError("Malformed JSON, duplicate keys or non-finite values") from exc
    bounded_json(value)
    return value


def pointer(parts) -> str:
    """Codificar ubicaciones segun JSON Pointer; '/' y '~' pueden ser nombres de campo."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def located_node(document: dict, node: Any, location: str) -> tuple[Any, str]:
    """Seguir refs de Path Item/Response sin expandir schemas recursivos ni tocar la red."""
    seen: set[str] = set()
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen:
            raise GuardError("Invalid or cyclic response/path reference")
        seen.add(ref)
        location = ref
        node = document
        try:
            for part in ref[2:].split("/"):
                node = node[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError) as exc:
            raise GuardError("Unresolvable local reference") from exc
    return node, location


def select_response(
    document: dict, path: str, method: str, status_code: int
) -> tuple[str, str, dict, str]:
    """Elegir ruta y respuesta: coincidencia exacta, rango de status y por ultimo default."""
    paths = document.get("paths", {})
    matched = path if path in paths else None
    if matched is None:
        candidates = []
        for template in paths:
            pattern = "".join(
                "[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
                for part in re.split(r"(\{[^{}]+\})", template)
            )
            if re.fullmatch(pattern, path):
                candidates.append(template)
        if len(candidates) > 1:
            raise GuardError("Ambiguous concrete path; supply the exact OpenAPI path template")
        matched = candidates[0] if candidates else None
    if matched is None:
        raise GuardError("Path is not declared in this contract", 404, "operation_not_found")
    path_item, path_pointer = located_node(
        document, paths[matched], "#" + pointer(["paths", matched])
    )
    operation = path_item.get(method.lower())
    if not isinstance(operation, dict):
        raise GuardError("Method is not declared for this path", 404, "operation_not_found")
    responses = operation.get("responses", {})
    key = next(
        (
            key
            for key in (str(status_code), f"{status_code // 100}XX", "default")
            if key in responses
        ),
        None,
    )
    if key is None:
        raise GuardError("Status code is not declared and has no matching range/default response")
    response, response_pointer = located_node(
        document, responses[key], path_pointer + pointer([method.lower(), "responses", key])
    )
    if not isinstance(response, dict):
        raise GuardError("Invalid response definition")
    return matched, key, response, response_pointer


def validate_openapi_response(
    document: dict,
    path: str,
    method: str,
    status_code: int,
    content_type: str,
    response_body: Any,
    body_present: bool,
    timeout: int = 30,
) -> dict:
    """Seleccionar el schema esperado; los datos reales se evaluan en un worker descartable."""
    if (
        document.get("jsonSchemaDialect") is not None
        and document["jsonSchemaDialect"] not in DIALECTS
    ):
        raise GuardError("The contract uses an unsupported JSON Schema dialect")
    bounded_json(document, schema=True)
    bounded_json(response_body)
    matched, status_key, response, response_pointer = select_response(
        document, path, method, status_code
    )
    media_type = content_type.split(";", 1)[0].strip().lower()
    selection = {
        "requested_path": path,
        "path_template": matched,
        "method": method.upper(),
        "status_code": status_code,
        "response_key": status_key,
        "content_type": media_type,
    }
    content = response.get("content", {})
    forbidden = method.lower() == "head" or status_code in (204, 205, 304) or status_code < 200
    if not body_present:
        if response_body is not None:
            raise GuardError("When body_present is false, response_body must be null")
        error = None if forbidden or not content else "body_missing"
        return presence_result(selection, error)
    if forbidden or not content:
        return presence_result(selection, "body_forbidden" if forbidden else "body_undeclared")
    if media_type != "application/json" and not (
        media_type.startswith("application/") and media_type.endswith("+json")
    ):
        raise GuardError("Only JSON response media types are supported", 415, "unsupported_format")
    media_key = next(
        (key for key in (media_type, media_type.split("/")[0] + "/*", "*/*") if key in content),
        None,
    )
    if media_key is None:
        raise GuardError("Content type is not declared for this response")
    if "schema" not in content[media_key]:
        raise GuardError("This response has no schema to validate; no validation was performed")
    schema_pointer = response_pointer + pointer(["content", media_key, "schema"])
    selection["media_type_key"] = media_key
    selection["schema_ref"] = schema_pointer
    dialect = "openapi30" if document["openapi"].startswith("3.0.") else "openapi31"
    result = run_validation(document, response_body, dialect, schema_pointer, timeout)
    return {**result, "selection": selection}


def presence_result(selection: dict, error: str | None) -> dict:
    messages = {
        "body_missing": "Expected a response body but none was supplied.",
        "body_forbidden": "This method/status must not include a response body.",
        "body_undeclared": "The contract declares no response content.",
    }
    return {
        "valid": error is None,
        "error_count": int(error is not None),
        "truncated": False,
        "validation_scope": "body_presence_only",
        "selection": selection,
        "errors": []
        if error is None
        else [{"path": "", "schema_path": "", "rule": error, "message": messages[error]}],
        "warnings": ["No JSON schema was evaluated; only response body presence was checked."],
    }


def validate_json_schema(schema: Any, response_body: Any, timeout: int = 30) -> dict:
    """Validacion independiente de OpenAPI/SQL; el informe no se persiste."""
    if not isinstance(schema, (dict, bool)):
        raise GuardError("Schema must be an object or boolean")
    if isinstance(schema, dict) and "openapi" in schema:
        raise GuardError(
            "Import the OpenAPI contract and use validate-response; this endpoint expects a JSON Schema"
        )
    bounded_json(schema, schema=True)
    bounded_json(response_body)
    return run_validation(schema, response_body, "jsonschema202012", None, timeout)


def _write_only(validator, schema, seen=None):
    # La libreria no sigue refs al decidir si un campo ausente es writeOnly.
    # Conservamos su resolver local (version fijada) para respetar ese caso.
    if not isinstance(schema, dict):
        return False
    if schema.get("writeOnly"):
        return True
    seen = set() if seen is None else seen
    ref = schema.get("$ref")
    if ref and ref not in seen:
        return _write_only(validator, validator._resolver.lookup(ref).contents, seen | {ref})
    return False


def _response_required(validator, required, instance, schema):
    if not validator.is_type(instance, "object"):
        return
    for key in required:
        if key not in instance and not _write_only(
            validator, schema.get("properties", {}).get(key)
        ):
            yield ValidationError("Required response property is missing.", path=[key])


def _response_write_only(validator, value, instance, schema):
    if value:
        yield ValidationError("A write-only property must not be present in a response.")


def _strip_dialects(value, names_map=False):
    """Copiar sin anotaciones de dialecto ya comprobadas, preservando nombres de campos.

    Evita que evolve() cambie de clase y pierda el contexto de respuesta read/write.
    Este recorrido ya crea una copia: no hace falta deepcopy antes de llamarlo.
    """
    if isinstance(value, dict):
        return {
            key: _strip_dialects(item, key in SCHEMA_MAP_KEYS and not names_map)
            for key, item in value.items()
            if names_map or key != "$schema"
        }
    if isinstance(value, list):
        return [_strip_dialects(item) for item in value]
    return value


def _worker(connection, document, body, dialect, schema_pointer):
    """Un proceso por evaluacion limita regex/recursion y nunca devuelve valores reales."""
    try:
        try:
            import resource

            getattr(resource, "setrlimit")(
                getattr(resource, "RLIMIT_AS"), (512 * 1024 * 1024, 512 * 1024 * 1024)
            )
        except ImportError:
            pass  # Windows: host/container policy plus a killable worker timeout.
        registry = Registry()  # No remote retriever: references can never fetch HTTP/files.
        document = _strip_dialects(document)
        if dialect == "jsonschema202012":
            cls = Draft202012Validator
            cls.check_schema(document)
        else:
            parent = OAS30ReadValidator if dialect == "openapi30" else OAS31Validator
            cls = extend(
                parent, {"required": _response_required, "writeOnly": _response_write_only}
            )
        validator = cls(document, registry=registry, format_checker=cls.FORMAT_CHECKER)
        if schema_pointer:
            validator = validator.evolve(schema={"$ref": schema_pointer})
        errors = []
        for error in islice(validator.iter_errors(body), MAX_ERRORS + 1):
            rule = str(error.validator or "schema")
            messages = {
                "type": f"Expected JSON type {error.validator_value}.",
                "required": "Required property is missing.",
                "writeOnly": "A write-only property must not be present in a response.",
                "additionalProperties": "Unexpected properties are not allowed.",
                "format": f"Value does not match format {error.validator_value}.",
            }
            errors.append(
                {
                    "path": pointer(error.absolute_path)[:2048],
                    "schema_path": pointer(error.absolute_schema_path)[:2048],
                    "rule": rule,
                    "message": messages.get(rule, f"Value violates the {rule} constraint.")[:300],
                }
            )
        truncated = len(errors) > MAX_ERRORS
        errors = errors[:MAX_ERRORS]
        errors.sort(key=lambda item: (item["path"], item["schema_path"], item["rule"]))
        connection.send(
            {
                "valid": not errors,
                "error_count": len(errors),
                "truncated": truncated,
                "validation_scope": "json_body",
                "errors": errors,
                "warnings": ["Unknown/custom formats are annotations and are not asserted."],
                "validator": {
                    "name": "jsonschema"
                    if dialect == "jsonschema202012"
                    else "openapi-schema-validator",
                    "version": version(
                        "jsonschema"
                        if dialect == "jsonschema202012"
                        else "openapi-schema-validator"
                    ),
                    "dialect": dialect,
                    "max_errors": MAX_ERRORS,
                },
            }
        )
    except Exception:
        connection.send(
            {
                "worker_error": "Schema could not be evaluated: invalid schema, unresolved reference or excessive recursion."
            }
        )
    finally:
        connection.close()


def run_validation(
    document: Any, body: Any, dialect: str, schema_pointer: str | None, timeout: int
) -> dict:
    """Aplicar concurrencia/timeout y cerrar proceso/pipes tambien si la evaluacion falla."""
    if not SLOTS.acquire(blocking=False):
        raise GuardError("Response validator is busy; retry shortly", 503, "validator_busy")
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_worker, args=(sender, document, body, dialect, schema_pointer), daemon=True
    )
    try:
        process.start()
        sender.close()
        if not receiver.poll(timeout):
            raise GuardError("Response validation timed out", 504, "validation_timeout")
        try:
            result = receiver.recv()
        except EOFError as exc:
            raise GuardError(
                "Response validation worker stopped", 422, "validation_execution_error"
            ) from exc
        if "worker_error" in result:
            raise GuardError(result["worker_error"], 422, "invalid_response_schema")
        return result
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=3)
            process.close()
        receiver.close()
        sender.close()
        SLOTS.release()
