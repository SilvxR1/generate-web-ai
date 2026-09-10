"""add review visibility

Revision ID: e7cb49c949cb
Revises: 05c0ddcd7fe5
Create Date: 2026-09-10 16:43:13.210894

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7cb49c949cb'
down_revision: Union[str, None] = '05c0ddcd7fe5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("business_reviews", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("business_reviews", schema=None) as batch_op:
        batch_op.drop_column("is_visible")
