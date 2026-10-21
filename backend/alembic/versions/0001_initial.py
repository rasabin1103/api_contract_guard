"""Initial standalone schema. Deliberately frozen, independent of application metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "contract_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("api_projects.id"), nullable=False),
        sa.Column("version_label", sa.String(100), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("specification_content", sa.Text(), nullable=False),
        sa.Column("openapi_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "version_label"),
        sa.UniqueConstraint("project_id", "content_hash"),
    )
    op.create_index("ix_contract_versions_project_id", "contract_versions", ["project_id"])
    op.create_table(
        "comparison_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("api_projects.id"), nullable=False),
        sa.Column(
            "baseline_id", sa.String(36), sa.ForeignKey("contract_versions.id"), nullable=False
        ),
        sa.Column(
            "candidate_id", sa.String(36), sa.ForeignKey("contract_versions.id"), nullable=False
        ),
        sa.Column("engine_version", sa.String(50), nullable=False),
        sa.Column("engine_configuration", sa.JSON(), nullable=False),
        sa.Column("overall_result", sa.String(30), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_comparison_runs_project_id", "comparison_runs", ["project_id"])
    op.create_table(
        "comparison_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "comparison_id", sa.String(36), sa.ForeignKey("comparison_runs.id"), nullable=False
        ),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_comparison_findings_comparison_id", "comparison_findings", ["comparison_id"]
    )


def downgrade():
    for name in ("comparison_findings", "comparison_runs", "contract_versions", "api_projects"):
        op.drop_table(name)
