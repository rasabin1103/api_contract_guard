"""Conexion SQL y sesiones: esquema mediante Alembic, no create_all en produccion."""

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import ensure_sqlite_directory


def create_session_factory(url: str) -> tuple[Engine, sessionmaker[Session]]:
    """Crear el pool sin abrir una sesion; SQLite debe activar explicitamente sus FK."""
    ensure_sqlite_directory(url)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine, sessionmaker(engine, expire_on_commit=False)
