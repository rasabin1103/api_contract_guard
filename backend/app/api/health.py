"""Liveness del servicio y conectividad de la base; no ejecuta oasdiff."""

from fastapi import APIRouter
from sqlalchemy import text

from app.api.dependencies import DB, EngineDependency

router = APIRouter(tags=["Service"])


@router.get("/health")
def health(db: DB, comparator: EngineDependency):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "mode": "single_user_local", "engine_version": comparator.version}
