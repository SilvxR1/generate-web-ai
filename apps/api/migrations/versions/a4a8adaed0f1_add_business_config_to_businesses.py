"""add business config to businesses

Revision ID: a4a8adaed0f1
Revises: c95f79055901
Create Date: 2026-08-25 21:38:55.637712

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4a8adaed0f1'
down_revision: Union[str, None] = 'c95f79055901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table: SQLite (local dev/tests) can't ALTER a table to
    # add a constraint in place the way Postgres (the real target) can —
    # batch mode does a copy-and-move on SQLite and is a transparent
    # passthrough to plain ALTER on Postgres, so this one migration works
    # correctly on both.
    with op.batch_alter_table("businesses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("slug", sa.String(length=100), nullable=False))
        batch_op.add_column(sa.Column("config", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("config_schema_version", sa.Integer(), nullable=False))
        batch_op.create_index(batch_op.f("ix_businesses_slug"), ["slug"], unique=False)
        batch_op.create_unique_constraint("uq_businesses_tenant_slug", ["tenant_id", "slug"])


def downgrade() -> None:
    with op.batch_alter_table("businesses", schema=None) as batch_op:
        batch_op.drop_constraint("uq_businesses_tenant_slug", type_="unique")
        batch_op.drop_index(batch_op.f("ix_businesses_slug"))
        batch_op.drop_column("config_schema_version")
        batch_op.drop_column("config")
        batch_op.drop_column("slug")
