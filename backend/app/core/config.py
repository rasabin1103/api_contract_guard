"""Configuracion por entorno ACG_ o backend/.env; no modifica variables del sistema."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ACG_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/guard.db"
    max_upload_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    comparison_timeout: int = Field(default=30, ge=1, le=300)
    oasdiff_path: str = "oasdiff"
    cors_origins: list[str] = Field(default_factory=list)


def ensure_sqlite_directory(url: str) -> None:
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
