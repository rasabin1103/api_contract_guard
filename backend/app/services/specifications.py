"""Importacion segura: conservar original, validar OpenAPI y calcular hash canonico."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import yaml
from openapi_spec_validator import validate
from yaml.tokens import AliasToken, AnchorToken

from app.core.json_input import load_json
from app.domain.models import GuardError


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader: UniqueLoader, node: yaml.MappingNode) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError("Object keys must be unique strings")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


@dataclass
class Specification:
    document: dict[str, Any]
    original: str
    content_hash: str
    openapi_version: str


def parse_specification(content: bytes, filename: str, limit: int) -> Specification:
    """Validar antes de persistir o ejecutar el motor; nunca recuperar referencias externas."""
    if len(content) > limit:
        raise GuardError("Specification exceeds the upload size limit", 413, "upload_too_large")
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension not in {"json", "yaml", "yml"}:
        raise GuardError("Use a .json, .yaml or .yml file", 415, "unsupported_format")
    try:
        original = content.decode("utf-8-sig")
        if extension == "json":
            document = load_json(original)
        else:
            if any(isinstance(t, (AliasToken, AnchorToken)) for t in yaml.scan(original)):
                raise ValueError("YAML anchors and aliases are not supported")
            document = yaml.load(original, Loader=UniqueLoader)
        if not isinstance(document, dict):
            raise ValueError("The document must be an object")
        version = str(document.get("openapi", ""))
        if not re.fullmatch(r"3\.(0|1)\.\d+", version):
            raise ValueError("Only OpenAPI 3.0.x and 3.1.x are supported")
        stack: list[tuple[Any, int]] = [(document, 0)]
        nodes = 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if depth > 64 or nodes > 100_000:
                raise ValueError("Specification exceeds structural complexity limits")
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"$dynamicRef", "$dynamicAnchor"}:
                        raise ValueError("Dynamic references are not supported by this engine")
                    if key == "$ref" and (not isinstance(item, str) or not item.startswith("#/")):
                        raise ValueError(
                            "Only local #/ references are allowed; remote/file refs blocked"
                        )
                    stack.append((item, depth + 1))
            elif isinstance(value, list):
                stack.extend((item, depth + 1) for item in value)
        if "pathItems" in document.get("components", {}):
            raise ValueError("Reusable components.pathItems are not supported by this engine")
        # Roundtrip also rejects YAML dates, non-string keys and non-finite floats.
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
        validate(document)
        return Specification(
            document, original, hashlib.sha256(canonical.encode()).hexdigest(), version
        )
    except GuardError:
        raise
    except Exception as exc:
        message = str(exc).split("\n")[0][:400] or type(exc).__name__
        raise GuardError(f"Invalid OpenAPI specification: {message}") from exc
