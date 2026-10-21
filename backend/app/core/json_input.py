"""Parsing JSON estricto compartido por contratos, datos reales y ficheros.

El parser estandar acepta NaN y conserva solo la ultima clave duplicada. En una
herramienta de contratos ambas cosas pueden ocultar errores, asi que se rechazan.
"""

import json
from typing import Any, NoReturn


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate object key")
        result[key] = value
    return result


def reject_nonfinite(_: str) -> NoReturn:
    raise ValueError("Non-finite numbers are forbidden")


def load_json(content: str | bytes) -> Any:
    """Leer UTF-8 (BOM opcional), sin coercion de tipos ni perdida de claves."""
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_nonfinite)
