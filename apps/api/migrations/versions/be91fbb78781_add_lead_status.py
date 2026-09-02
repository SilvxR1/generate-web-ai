"""add lead status

Revision ID: be91fbb78781
Revises: a7c4e1f9d3b2
Create Date: 2026-09-02 18:27:39.852937

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be91fbb78781'
down_revision: Union[str, None] = 'a7c4e1f9d3b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.Enum("new", "contacted", "won", "lost", name="leadstatus", native_enum=False, length=20),
                nullable=False,
                server_default="new",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_column("status")
