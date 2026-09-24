"""add creative_generations.website_direction (A8.2.4)

Adds one nullable JSON column holding the normalized WebsiteCreativeDirection
v1 a generation produced (app.domain.creative.website_direction). Purely
additive: no backfill, existing rows stay NULL (historical absence is valid
— no direction is ever reconstructed for an old generation), and downgrade
removes only this column.

Revision ID: c4d7e2a9f1b3
Revises: b1e2f9a08c3d
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d7e2a9f1b3'
down_revision: Union[str, None] = 'b1e2f9a08c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("creative_generations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("website_direction", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("creative_generations", schema=None) as batch_op:
        batch_op.drop_column("website_direction")
