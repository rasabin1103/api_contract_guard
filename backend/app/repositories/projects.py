"""Adaptador local de acceso a proyectos; la interfaz es el punto de reemplazo futuro."""

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project
from app.domain.models import GuardError


class ProjectRepository(Protocol):
    """Un adaptador autenticado futuro debera aplicar organizacion en cada metodo."""

    def get(self, project_id: str) -> Project: ...


class LocalProjectRepository:
    """Modo monousuario explicito; no implementa aislamiento de organizaciones."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, project_id: str) -> Project:
        project = self.session.scalar(select(Project).where(Project.id == project_id))
        if project is None:
            raise GuardError("Project not found", 404, "not_found")
        return project
