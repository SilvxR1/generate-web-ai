"""add generation job source (v0.2 R4.1)

The isolated execution host builds from a job's generated SOURCE archive
(private storage key + SHA-256) and the public API origin. Purely
additive, nullable, no backfill; downgrade drops only these columns.

Revision ID: c8f4a1d6e2b9
Revises: a4d2e8f1c7b3
Create Date: 2026-09-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f4a1d6e2b9'
down_revision: Union[str, None] = 'a4d2e8f1c7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("generation_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_key", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("source_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("api_base_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs", schema=None) as batch_op:
        batch_op.drop_column("api_base_url")
        batch_op.drop_column("source_sha256")
        batch_op.drop_column("source_key")
