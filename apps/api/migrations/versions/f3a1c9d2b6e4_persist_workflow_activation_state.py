"""persist workflow activation state

Revision ID: f3a1c9d2b6e4
Revises: e8548498ac24
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a1c9d2b6e4'
down_revision: Union[str, None] = 'e8548498ac24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workflows", schema=None) as batch_op:
        batch_op.add_column(sa.Column("local_workflow_id", sa.String(length=120), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("required_capabilities", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column("local_workflow_id", server_default=None)
        batch_op.alter_column("version", server_default=None)
        batch_op.alter_column("required_capabilities", server_default=None)
        batch_op.create_unique_constraint(
            "uq_workflows_business_local_workflow_id", ["business_id", "local_workflow_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("workflows", schema=None) as batch_op:
        batch_op.drop_constraint("uq_workflows_business_local_workflow_id", type_="unique")
        batch_op.drop_column("activated_at")
        batch_op.drop_column("required_capabilities")
        batch_op.drop_column("version")
        batch_op.drop_column("local_workflow_id")
