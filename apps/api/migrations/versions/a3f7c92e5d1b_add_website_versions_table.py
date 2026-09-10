"""add website_versions table

Revision ID: a3f7c92e5d1b
Revises: f1c5b8e347a2
Create Date: 2026-09-10 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f7c92e5d1b'
down_revision: Union[str, None] = 'f1c5b8e347a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "website_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "business_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("website_id", sa.Uuid(as_uuid=True), sa.ForeignKey("websites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("site_config", sa.JSON(), nullable=False),
        sa.Column("deploy_url", sa.String(length=2048), nullable=False),
        sa.Column("provider_deployment_id", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_website_versions_tenant_id", "website_versions", ["tenant_id"])
    op.create_index("ix_website_versions_business_id", "website_versions", ["business_id"])
    op.create_index("ix_website_versions_website_id", "website_versions", ["website_id"])


def downgrade() -> None:
    op.drop_index("ix_website_versions_website_id", table_name="website_versions")
    op.drop_index("ix_website_versions_business_id", table_name="website_versions")
    op.drop_index("ix_website_versions_tenant_id", table_name="website_versions")
    op.drop_table("website_versions")
