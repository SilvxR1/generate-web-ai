"""add notification delivery status

Revision ID: a851022e3955
Revises: a3f7c92e5d1b
Create Date: 2026-09-10 16:21:08.003889

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a851022e3955'
down_revision: Union[str, None] = 'a3f7c92e5d1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    status_enum = sa.Enum(
        "pending", "sent", "failed", "not_configured", name="notificationdeliverystatus", native_enum=False, length=20
    )
    with op.batch_alter_table("internal_notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("status", status_enum, nullable=False, server_default="pending"))
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("acknowledgement_status", status_enum, nullable=False, server_default="pending"))


def downgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_column("acknowledgement_status")
    with op.batch_alter_table("internal_notifications", schema=None) as batch_op:
        batch_op.drop_column("status")
