"""add P2 creative_directions/generative_website_artifacts tables and website_drafts.engine

Revision ID: c1d9f6a4b8e7
Revises: 7bccea75808f
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d9f6a4b8e7'
down_revision: Union[str, None] = '7bccea75808f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "creative_directions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", sa.Uuid(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "creative_generation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("creative_generations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("concept", sa.JSON(), nullable=False),
        sa.Column("visual_language", sa.JSON(), nullable=False),
        sa.Column("experience", sa.JSON(), nullable=False),
        sa.Column("content_strategy", sa.JSON(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("provider_metadata", sa.JSON(), nullable=False),
        sa.Column("generation_metadata", sa.JSON(), nullable=False),
        sa.Column("is_recommended", sa.Boolean(), nullable=False),
        sa.Column("selection_rationale", sa.Text(), nullable=True),
        sa.Column("credits_used", sa.Float(), nullable=True),
        sa.Column("developed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_creative_directions_tenant_id", "creative_directions", ["tenant_id"])
    op.create_index("ix_creative_directions_business_id", "creative_directions", ["business_id"])
    op.create_index("ix_creative_directions_creative_generation_id", "creative_directions", ["creative_generation_id"])

    # batch_alter_table: SQLite has no native ALTER COLUMN — Alembic's
    # batch mode rebuilds the table under the hood, the same approach
    # every other nullable-change migration in this codebase would need
    # on SQLite (the zero-config local-dev/test database; see
    # app.config.Settings.database_url's own docstring). Also safe on
    # Postgres (every real deployment), where batch mode transparently
    # falls back to plain ALTER COLUMN.
    with op.batch_alter_table("website_drafts") as batch_op:
        batch_op.add_column(
            sa.Column("engine", sa.String(length=20), nullable=False, server_default="deterministic")
        )
        batch_op.alter_column("site_config", existing_type=sa.JSON(), nullable=True)

    op.create_table(
        "generative_website_artifacts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", sa.Uuid(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "website_draft_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("website_drafts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "creative_direction_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("creative_directions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("framework", sa.String(length=50), nullable=False),
        sa.Column("workspace_key", sa.String(length=300), nullable=False),
        sa.Column("build_command", sa.String(length=300), nullable=False),
        sa.Column("output_dir", sa.String(length=300), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("platform_contract_version", sa.String(length=20), nullable=False),
        sa.Column("qa_state", sa.JSON(), nullable=False),
        sa.Column("generator_provider", sa.String(length=50), nullable=False),
        sa.Column("generator_model", sa.String(length=100), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_generative_website_artifacts_tenant_id", "generative_website_artifacts", ["tenant_id"])
    op.create_index("ix_generative_website_artifacts_business_id", "generative_website_artifacts", ["business_id"])
    op.create_index(
        "ix_generative_website_artifacts_website_draft_id", "generative_website_artifacts", ["website_draft_id"]
    )
    op.create_index(
        "ix_generative_website_artifacts_creative_direction_id",
        "generative_website_artifacts",
        ["creative_direction_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_generative_website_artifacts_creative_direction_id", table_name="generative_website_artifacts")
    op.drop_index("ix_generative_website_artifacts_website_draft_id", table_name="generative_website_artifacts")
    op.drop_index("ix_generative_website_artifacts_business_id", table_name="generative_website_artifacts")
    op.drop_index("ix_generative_website_artifacts_tenant_id", table_name="generative_website_artifacts")
    op.drop_table("generative_website_artifacts")

    with op.batch_alter_table("website_drafts") as batch_op:
        batch_op.alter_column("site_config", existing_type=sa.JSON(), nullable=False)
        batch_op.drop_column("engine")

    op.drop_index("ix_creative_directions_creative_generation_id", table_name="creative_directions")
    op.drop_index("ix_creative_directions_business_id", table_name="creative_directions")
    op.drop_index("ix_creative_directions_tenant_id", table_name="creative_directions")
    op.drop_table("creative_directions")
