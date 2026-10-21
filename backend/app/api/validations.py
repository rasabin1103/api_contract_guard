"""Validacion puntual de respuestas: ni los cuerpos ni los resultados se persisten."""

from uuid import UUID

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import DB, SettingsDependency
from app.api.queries import contract, project
from app.schemas.api import ResponseValidationInput, ResponseValidationReport, SchemaValidationInput
from app.services.response_validation import (
    parse_json_file,
    validate_json_schema,
    validate_openapi_response,
)
from app.services.specifications import parse_specification

router = APIRouter(tags=["Response validation"])


@router.post(
    "/api/v1/projects/{project_id}/contracts/{version_id}/validate-response",
    response_model=ResponseValidationReport,
    response_model_exclude_none=True,
    summary="Validate captured JSON against an imported OpenAPI response",
)
def validate_contract_response(
    project_id: UUID,
    version_id: UUID,
    body: ResponseValidationInput,
    db: DB,
    settings: SettingsDependency,
):
    project(db, project_id)
    value = contract(db, str(project_id), str(version_id))
    specification = parse_specification(
        value.specification_content.encode(), value.original_filename, settings.max_upload_bytes
    )
    result = validate_openapi_response(
        specification.document,
        body.path,
        body.method,
        body.status_code,
        body.content_type,
        body.response_body,
        body.body_present,
        settings.comparison_timeout,
    )
    return {
        **result,
        "project_id": str(project_id),
        "contract_id": value.id,
        "version_label": value.version_label,
        "content_hash": value.content_hash,
    }


@router.post(
    "/api/v1/validations/schema",
    response_model=ResponseValidationReport,
    response_model_exclude_none=True,
    summary="Validate JSON data against a standalone JSON Schema (2020-12)",
)
def validate_schema(body: SchemaValidationInput, settings: SettingsDependency):
    return validate_json_schema(
        body.schema_document, body.response_body, settings.comparison_timeout
    )


@router.post(
    "/api/v1/validations/schema/files",
    response_model=ResponseValidationReport,
    response_model_exclude_none=True,
    summary="Upload a schema.json and response.json for stateless validation",
)
async def validate_schema_files(
    settings: SettingsDependency,
    schema_file: UploadFile = File(...),
    response_file: UploadFile = File(...),
):
    try:
        schema_content = await schema_file.read(settings.max_upload_bytes + 1)
        response_content = await response_file.read(settings.max_upload_bytes + 1)
    finally:
        await schema_file.close()
        await response_file.close()
    schema = parse_json_file(schema_content, schema_file.filename or "", settings.max_upload_bytes)
    response = parse_json_file(
        response_content, response_file.filename or "", settings.max_upload_bytes
    )
    return await run_in_threadpool(
        validate_json_schema, schema, response, settings.comparison_timeout
    )
