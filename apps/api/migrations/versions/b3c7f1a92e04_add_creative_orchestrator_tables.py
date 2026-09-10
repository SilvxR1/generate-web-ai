"""add creative orchestrator tables (business_assets, business_reviews, creative_generations)

Revision ID: b3c7f1a92e04
Revises: be91fbb78781
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c7f1a92e04'
down_revision: Union[str, None] = 'be91fbb78781'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "creative_generations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", sa.Uuid(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("generation_type", sa.String(length=30), nullable=False),
        sa.Column("creative_level", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("external_reference", sa.String(length=300), nullable=True),
        sa.Column("credits_used", sa.Float(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("generation_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_creative_generations_tenant_id", "creative_generations", ["tenant_id"])
    op.create_index("ix_creative_generations_business_id", "creative_generations", ["business_id"])

    op.create_table(
        "business_assets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", sa.Uuid(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("storage_url", sa.String(length=2048), nullable=False),
        sa.Column("original_filename", sa.String(length=300), nullable=True),
        sa.Column("alt_text", sa.String(length=300), nullable=True),
        sa.Column("asset_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "generation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("creative_generations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_business_assets_tenant_id", "business_assets", ["tenant_id"])
    op.create_index("ix_business_assets_business_id", "business_assets", ["business_id"])

    op.create_table(
        "business_reviews",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", sa.Uuid(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_review_id", sa.String(length=300), nullable=True),
        sa.Column("author_name", sa.String(length=200), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("review_url", sa.String(length=2048), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_id", "source", "source_review_id", name="uq_business_reviews_source_review"),
    )
    op.create_index("ix_business_reviews_tenant_id", "business_reviews", ["tenant_id"])
    op.create_index("ix_business_reviews_business_id", "business_reviews", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_business_reviews_business_id", table_name="business_reviews")
    op.drop_index("ix_business_reviews_tenant_id", table_name="business_reviews")
    op.drop_table("business_reviews")

    op.drop_index("ix_business_assets_business_id", table_name="business_assets")
    op.drop_index("ix_business_assets_tenant_id", table_name="business_assets")
    op.drop_table("business_assets")

    op.drop_index("ix_creative_generations_business_id", table_name="creative_generations")
    op.drop_index("ix_creative_generations_tenant_id", table_name="creative_generations")
    op.drop_table("creative_generations")
