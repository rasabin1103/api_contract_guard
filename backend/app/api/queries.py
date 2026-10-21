"""Lecturas acotadas por proyecto y proyecciones HTTP; no exponen datos de otro proyecto."""

from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.db.models import Comparison, Contract, Project, StoredFinding
from app.domain.models import GuardError
from app.repositories.projects import LocalProjectRepository, ProjectRepository


def project(db: Session, identifier: UUID) -> Project:
    repository: ProjectRepository = LocalProjectRepository(db)
    return repository.get(str(identifier))


def contract(
    db: Session, project_id: str, identifier: str, *, include_content: bool = True
) -> Contract:
    """Exigir siempre el proyecto, aunque el contrato se busque por UUID."""
    query = select(Contract).where(Contract.project_id == project_id, Contract.id == identifier)
    if not include_content:
        query = query.options(defer(Contract.specification_content))
    value = db.scalar(query)
    if value is None:
        raise GuardError("Contract not found in this project", 404, "not_found")
    return value


def report(db: Session, identifier: UUID) -> dict:
    """Reconstruir un informe guardado; no ejecutar el motor ni cargar textos de contratos."""
    run = db.get(Comparison, str(identifier))
    if run is None:
        raise GuardError("Comparison not found", 404, "not_found")
    data = jsonable_encoder(run)
    data["project"] = jsonable_encoder(db.get(Project, run.project_id))
    data["baseline"] = contract_summary(
        contract(db, run.project_id, run.baseline_id, include_content=False)
    )
    data["candidate"] = contract_summary(
        contract(db, run.project_id, run.candidate_id, include_content=False)
    )
    data["engine"] = {
        "name": "oasdiff",
        "version": run.engine_version,
        "configuration": run.engine_configuration,
    }
    data["findings"] = [
        row.data
        for row in db.scalars(select(StoredFinding).where(StoredFinding.comparison_id == run.id))
    ]
    data["findings"].sort(key=lambda f: (f["location"], f["rule_id"], f["id"]))
    return data


def contract_summary(value: Contract) -> dict:
    """Proyectar solo metadatos: no leer ni serializar el texto de la especificacion."""
    return jsonable_encoder(
        {
            name: getattr(value, name)
            for name in (
                "id",
                "project_id",
                "version_label",
                "original_filename",
                "content_hash",
                "openapi_version",
                "created_at",
            )
        }
    )
