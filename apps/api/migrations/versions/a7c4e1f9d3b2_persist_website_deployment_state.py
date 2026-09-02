"""persist website deployment state

Revision ID: a7c4e1f9d3b2
Revises: f3a1c9d2b6e4
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c4e1f9d3b2'
down_revision: Union[str, None] = 'f3a1c9d2b6e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("websites", schema=None) as batch_op:
        batch_op.add_column(sa.Column("provider_deployment_id", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("websites", schema=None) as batch_op:
        batch_op.drop_column("deployed_at")
        batch_op.drop_column("provider_deployment_id")
