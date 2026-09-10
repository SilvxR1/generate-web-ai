"""extend leads for public intake (subject, source_url, consent, metadata)

Revision ID: e7a2b9c1d5f0
Revises: d4f8e2c17a63
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a2b9c1d5f0'
down_revision: Union[str, None] = 'd4f8e2c17a63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subject", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("source_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(
            sa.Column("consent_given", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("lead_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_column("lead_metadata")
        batch_op.drop_column("consent_given")
        batch_op.drop_column("source_url")
        batch_op.drop_column("subject")
