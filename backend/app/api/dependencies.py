"""Dependencias compartidas de FastAPI; cada peticion obtiene su propia sesion SQL."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.models import ComparisonEngine


def session(request: Request) -> Generator[Session, None, None]:
    """Cerrar la sesion tambien al fallar: una transaccion sin commit se revierte."""
    with request.app.state.session_factory() as database_session:
        yield database_session


def settings(request: Request) -> Settings:
    return request.app.state.settings


def comparison_engine(request: Request) -> ComparisonEngine:
    return request.app.state.comparison_engine


# Aliases usados por todas las rutas: no hay factorias o sesiones globales ocultas.
DB = Annotated[Session, Depends(session)]
SettingsDependency = Annotated[Settings, Depends(settings)]
EngineDependency = Annotated[ComparisonEngine, Depends(comparison_engine)]
