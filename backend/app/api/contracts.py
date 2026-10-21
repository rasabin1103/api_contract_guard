"""Importacion y consulta de versiones inmutables de contratos OpenAPI."""

import re
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import defer
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import DB, SettingsDependency
from app.api.queries import contract, contract_summary, project
from app.db.models import Contract
from app.domain.models import GuardError
from app.services.specifications import parse_specification

router = APIRouter(tags=["Contracts"])


@router.post("/api/v1/projects/{project_id}/contracts", status_code=201)
async def import_contract(
    project_id: UUID,
    db: DB,
    settings: SettingsDependency,
    version_label: str = Form(..., min_length=1, max_length=100),
    file: UploadFile = File(...),
):
    """Validar primero; un error no deja una version parcial en la base de datos."""
    project(db, project_id)
    if not version_label.strip():
        raise GuardError("Version label cannot be blank")
    filename = re.split(r"[/\\]", file.filename or "")[-1][:255]
    try:
        content = await file.read(settings.max_upload_bytes + 1)
    finally:
        await file.close()
    spec = await run_in_threadpool(
        parse_specification, content, filename, settings.max_upload_bytes
    )
    value = Contract(
        project_id=str(project_id),
        version_label=version_label.strip(),
        original_filename=filename,
        content_hash=spec.content_hash,
        specification_content=spec.original,
        openapi_version=spec.openapi_version,
    )
    db.add(value)
    db.commit()
    return contract_summary(value)


@router.get("/api/v1/projects/{project_id}/contracts")
def contracts(
    project_id: UUID, db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
):
    project(db, project_id)
    values = db.scalars(
        select(Contract)
        .options(defer(Contract.specification_content))
        .where(Contract.project_id == str(project_id))
        .order_by(Contract.created_at.desc(), Contract.id)
        .offset(offset)
        .limit(limit)
    )
    return [contract_summary(value) for value in values]


@router.get("/api/v1/projects/{project_id}/contracts/{version_id}")
def get_contract(project_id: UUID, version_id: UUID, db: DB):
    project(db, project_id)
    return contract(db, str(project_id), str(version_id))
