"""Punto de entrada: configurar dependencias y conectar rutas, sin logica de negocio.

Arranque de desarrollo (desde backend/):
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

La CLI utiliza los servicios directamente y nunca necesita importar este modulo.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.adapters.oasdiff import OasdiffEngine
from app.api import comparisons, contracts, health, projects, validations
from app.api.http import configure_http
from app.core.config import Settings
from app.db.session import create_session_factory
from app.domain.models import ComparisonEngine


def create_app(settings: Settings | None = None, engine: ComparisonEngine | None = None) -> FastAPI:
    """Crear una API independiente; las pruebas pueden inyectar configuracion y motor."""
    settings = settings or Settings()
    database, session_factory = create_session_factory(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            database.dispose()

    application = FastAPI(
        title="ASE API Contract Guard",
        version="0.2.0",
        description=(
            "API independiente, sin frontend propio. Compara contratos OpenAPI o valida "
            "respuestas JSON capturadas contra un contrato/esquema. "
            "HTTP 200 indica que la evaluacion termino: consulta valid para saber si los datos cumplen."
        ),
        lifespan=lifespan,
    )
    # Un unico lugar para construir recursos. Las rutas los reciben mediante Depends.
    application.state.database = database
    application.state.session_factory = session_factory
    application.state.settings = settings
    application.state.comparison_engine = engine or OasdiffEngine(
        settings.oasdiff_path, settings.comparison_timeout
    )
    configure_http(application, settings)
    for router in (
        health.router,
        projects.router,
        contracts.router,
        comparisons.router,
        validations.router,
    ):
        application.include_router(router)

    @application.get("/", include_in_schema=False)
    def documentation():
        return RedirectResponse("/docs")

    return application


app = create_app()
