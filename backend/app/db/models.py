"""Cuatro tablas portables entre SQLite/PostgreSQL; cambiar esquema requiere migracion."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


def identifier() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "api_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Contract(Base):
    __tablename__ = "contract_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_label"),
        UniqueConstraint("project_id", "content_hash"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    project_id: Mapped[str] = mapped_column(ForeignKey("api_projects.id"), index=True)
    version_label: Mapped[str] = mapped_column(String(100))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    specification_content: Mapped[str] = mapped_column(Text)
    openapi_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Comparison(Base):
    __tablename__ = "comparison_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    project_id: Mapped[str] = mapped_column(ForeignKey("api_projects.id"), index=True)
    baseline_id: Mapped[str] = mapped_column(ForeignKey("contract_versions.id"))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("contract_versions.id"))
    engine_version: Mapped[str] = mapped_column(String(50))
    engine_configuration: Mapped[dict[str, Any]] = mapped_column(JSON)
    overall_result: Mapped[str] = mapped_column(String(30))
    summary: Mapped[dict[str, int]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StoredFinding(Base):
    __tablename__ = "comparison_findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("comparison_runs.id"), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
