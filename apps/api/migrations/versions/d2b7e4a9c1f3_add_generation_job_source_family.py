"""add generation job source family (H1.1)

The trusted source family of a generation job selects the site's CSP
additions (app.publishing.csp_policy). Purely additive: NOT NULL with a
server default of 'gwa-astro' (the GWA baseline, i.e. exactly today's
behavior) so every existing row keeps its current policy; downgrade drops
only this column.

Revision ID: d2b7e4a9c1f3
Revises: c8f4a1d6e2b9
Create Date: 2026-09-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2b7e4a9c1f3'
down_revision: Union[str, None] = 'c8f4a1d6e2b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("generation_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source_family", sa.String(length=64), nullable=False, server_default="gwa-astro")
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs", schema=None) as batch_op:
        batch_op.drop_column("source_family")
