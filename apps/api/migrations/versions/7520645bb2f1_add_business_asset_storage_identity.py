"""add business asset storage identity and availability

Revision ID: 7520645bb2f1
Revises: e7a1b3c5d9f2
Create Date: 2026-09-13 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7520645bb2f1'
down_revision: Union[str, None] = 'e7a1b3c5d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("business_assets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("storage_provider", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("storage_key", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("unavailable_reason", sa.String(300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("business_assets", schema=None) as batch_op:
        batch_op.drop_column("unavailable_reason")
        batch_op.drop_column("storage_key")
        batch_op.drop_column("storage_provider")
