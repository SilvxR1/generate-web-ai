"""add website_drafts table

Revision ID: d4f8e2c17a63
Revises: b3c7f1a92e04
Create Date: 2026-09-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f8e2c17a63'
down_revision: Union[str, None] = 'b3c7f1a92e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "website_drafts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", sa.Uuid(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "creative_generation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("creative_generations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("site_config", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("build_error", sa.Text(), nullable=True),
        sa.Column("validation_issues", sa.JSON(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "published_website_id", sa.Uuid(as_uuid=True), sa.ForeignKey("websites.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_website_drafts_tenant_id", "website_drafts", ["tenant_id"])
    op.create_index("ix_website_drafts_business_id", "website_drafts", ["business_id"])
    op.create_index("ix_website_drafts_creative_generation_id", "website_drafts", ["creative_generation_id"])


def downgrade() -> None:
    op.drop_index("ix_website_drafts_creative_generation_id", table_name="website_drafts")
    op.drop_index("ix_website_drafts_business_id", table_name="website_drafts")
    op.drop_index("ix_website_drafts_tenant_id", table_name="website_drafts")
    op.drop_table("website_drafts")
