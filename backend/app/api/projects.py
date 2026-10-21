"""Gestion de proyectos locales; el borrado exige confirmar el nombre exacto."""

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import delete, select

from app.api.dependencies import DB
from app.api.queries import project
from app.db.models import Comparison, Contract, Project, StoredFinding
from app.domain.models import GuardError
from app.schemas.api import ProjectInput, ProjectPatch

router = APIRouter(tags=["Projects"])


@router.get("/api/v1/projects")
def projects(db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    return list(
        db.scalars(
            select(Project)
            .order_by(Project.created_at.desc(), Project.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.post("/api/v1/projects", status_code=201)
def create_project(body: ProjectInput, db: DB):
    value = Project(**body.model_dump())
    db.add(value)
    db.commit()
    return value


@router.get("/api/v1/projects/{project_id}")
def get_project(project_id: UUID, db: DB):
    return project(db, project_id)


@router.patch("/api/v1/projects/{project_id}")
def patch_project(project_id: UUID, body: ProjectPatch, db: DB):
    value = project(db, project_id)
    changes = body.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise GuardError("Fields cannot be null")
    # ProjectPatch ya valida/normaliza estos campos y prohibe claves adicionales.
    for field, updated_value in changes.items():
        setattr(value, field, updated_value)
    db.commit()
    return value


@router.delete("/api/v1/projects/{project_id}", status_code=204)
def delete_project(project_id: UUID, db: DB, confirm_name: str = Query(...)):
    value = project(db, project_id)
    if confirm_name != value.name:
        raise GuardError("Confirmation must match the project name", 409, "confirmation_required")
    runs = select(Comparison.id).where(Comparison.project_id == value.id)
    # Orden inverso a las FK; un solo commit hace que el borrado sea atomico.
    db.execute(delete(StoredFinding).where(StoredFinding.comparison_id.in_(runs)))
    db.execute(delete(Comparison).where(Comparison.project_id == value.id))
    db.execute(delete(Contract).where(Contract.project_id == value.id))
    db.delete(value)
    db.commit()
    return Response(status_code=204)
