"""add custom_domains table

Revision ID: f1c5b8e347a2
Revises: e7a2b9c1d5f0
Create Date: 2026-09-10 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1c5b8e347a2'
down_revision: Union[str, None] = 'e7a2b9c1d5f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "custom_domains",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "business_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider_status", sa.String(length=100), nullable=True),
        sa.Column("cname_target", sa.String(length=253), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_id", name="uq_custom_domains_business_id"),
    )
    op.create_index("ix_custom_domains_tenant_id", "custom_domains", ["tenant_id"])
    op.create_index("ix_custom_domains_business_id", "custom_domains", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_custom_domains_business_id", table_name="custom_domains")
    op.drop_index("ix_custom_domains_tenant_id", table_name="custom_domains")
    op.drop_table("custom_domains")
