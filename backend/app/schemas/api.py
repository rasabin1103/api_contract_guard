"""Modelos del contrato HTTP: Pydantic valida entradas y genera la documentacion Swagger."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, field_validator


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class ProjectPatch(BaseModel):
    """Campos omitidos no cambian: las rutas usan exclude_unset para un PATCH parcial."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip() if value else value


class ComparisonInput(BaseModel):
    """El orden importa: baseline es el contrato actual y candidate la propuesta."""

    model_config = ConfigDict(extra="forbid")
    baseline_id: UUID
    candidate_id: UUID


class ResponseValidationInput(BaseModel):
    """Datos reales sin coercion; JSON null se distingue de ausencia de cuerpo."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "path": "/items",
                "method": "GET",
                "status_code": 200,
                "content_type": "application/json",
                "response_body": {"id": "123", "name": "Ana"},
                "body_present": True,
            }
        },
    )
    path: str = Field(
        min_length=1,
        max_length=2048,
        description="OpenAPI path template or concrete path, without query string",
    )
    method: str = Field(
        default="GET", pattern=r"^(?i:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)$"
    )
    status_code: int = Field(default=200, ge=100, le=599, strict=True)
    content_type: str = Field(default="application/json", min_length=1, max_length=200)
    response_body: JsonValue = Field(
        ...,
        description="Actual JSON data; no coercion. null is a JSON body unless body_present=false.",
    )
    body_present: bool = Field(default=True, strict=True)

    @field_validator("path")
    @classmethod
    def path_only(cls, value: str) -> str:
        if not value.startswith("/") or "?" in value or "#" in value:
            raise ValueError("Use a path starting with /, without query string or fragment")
        return value


class SchemaValidationInput(BaseModel):
    """JSON Schema formal, no un ejemplo de datos ni un documento OpenAPI completo."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "schema": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "integer"}},
                },
                "response_body": {"id": "123"},
            }
        },
    )
    schema_document: dict[str, Any] | StrictBool = Field(
        alias="schema",
        description="JSON Schema 2020-12, not sample data or OpenAPI. {} and true accept any JSON.",
    )
    response_body: JsonValue = Field(...)


class ResponseValidationIssue(BaseModel):
    path: str = Field(description="JSON Pointer into the captured response; empty means root")
    schema_path: str
    rule: str
    message: str


class ResponseValidationReport(BaseModel):
    """HTTP 200 indica evaluacion completada; valid determina si los datos cumplen."""

    valid: bool
    error_count: int = Field(
        description="Number of returned errors (maximum 100), not an unbounded total"
    )
    truncated: bool
    validation_scope: Literal["json_body", "body_presence_only"]
    errors: list[ResponseValidationIssue]
    warnings: list[str]
    validator: dict[str, Any] | None = None
    selection: dict[str, Any] | None = None
    project_id: UUID | None = None
    contract_id: UUID | None = None
    version_label: str | None = None
    content_hash: str | None = None
