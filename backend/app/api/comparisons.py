"""Comparaciones persistentes e historial; nunca se recalculan informes al consultarlos."""

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.dependencies import DB, EngineDependency, SettingsDependency
from app.api.queries import contract, project, report
from app.db.models import Comparison, StoredFinding
from app.schemas.api import ComparisonInput
from app.services.comparisons import summarize
from app.services.specifications import parse_specification

router = APIRouter(tags=["Comparisons"])


@router.post("/api/v1/projects/{project_id}/comparisons", status_code=201)
def compare(
    project_id: UUID,
    body: ComparisonInput,
    db: DB,
    comparator: EngineDependency,
    settings: SettingsDependency,
):
    """Comparar baseline -> candidato y guardar ejecucion/hallazgos en una transaccion."""
    project(db, project_id)
    baseline = contract(db, str(project_id), str(body.baseline_id))
    candidate = (
        baseline
        if body.baseline_id == body.candidate_id
        else contract(db, str(project_id), str(body.candidate_id))
    )
    # Validar de nuevo conserva la politica actual para versiones importadas antes de una actualizacion.
    baseline_spec = parse_specification(
        baseline.specification_content.encode(),
        baseline.original_filename,
        settings.max_upload_bytes,
    )
    candidate_spec = (
        baseline_spec
        if candidate is baseline
        else parse_specification(
            candidate.specification_content.encode(),
            candidate.original_filename,
            settings.max_upload_bytes,
        )
    )
    findings = comparator.compare(baseline_spec.document, candidate_spec.document)
    result, summary = summarize(findings)
    run = Comparison(
        project_id=str(project_id),
        baseline_id=baseline.id,
        candidate_id=candidate.id,
        engine_version=comparator.version,
        engine_configuration=comparator.configuration,
        overall_result=result,
        summary=summary,
    )
    db.add(run)
    db.flush()
    for finding in findings:
        db.add(StoredFinding(comparison_id=run.id, data=finding.to_dict()))
    db.commit()
    # SQLite normaliza fechas al leerlas. Refrescar solo la ejecucion evita invalidar toda la sesion.
    db.refresh(run)
    return report(db, UUID(run.id))


@router.get("/api/v1/projects/{project_id}/comparisons")
def history(
    project_id: UUID, db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
):
    project(db, project_id)
    return list(
        db.scalars(
            select(Comparison)
            .where(Comparison.project_id == str(project_id))
            .order_by(Comparison.created_at.desc(), Comparison.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.get("/api/v1/comparisons/{comparison_id}")
def get_report(comparison_id: UUID, db: DB):
    return report(db, comparison_id)


@router.get("/api/v1/comparisons/{comparison_id}/export")
def export_report(comparison_id: UUID, db: DB):
    return JSONResponse(
        jsonable_encoder(report(db, comparison_id)),
        headers={"Content-Disposition": f'attachment; filename="comparison-{comparison_id}.json"'},
    )
