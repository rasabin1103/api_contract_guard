"""Contratos internos: tipos y errores independientes de HTTP, SQL y ASE."""

from dataclasses import asdict, dataclass
from typing import Any, Protocol


class GuardError(Exception):
    """Error esperado que HTTP traduce a un codigo y CLI a salida 2."""

    def __init__(self, message: str, status: int = 422, code: str = "validation_error"):
        self.message, self.status, self.code = message, status, code
        super().__init__(message)


@dataclass
class Finding:
    """Hallazgo normalizado; conserva la regla/metadatos del motor para trazabilidad."""

    id: str
    rule_id: str
    category: str
    severity: str
    location: str
    description: str
    previous_value: Any
    current_value: Any
    recommendation: str
    engine_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComparisonEngine(Protocol):
    """Interfaz minima para sustituir oasdiff sin cambiar API/CLI/persistencia."""

    version: str
    configuration: dict[str, Any]

    def compare(self, base: dict[str, Any], target: dict[str, Any]) -> list[Finding]: ...
