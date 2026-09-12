"""add leads.automation_dispatch_status (P2 canonical lead API)

Revision ID: d2e4f8a1c6b9
Revises: c1d9f6a4b8e7
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e4f8a1c6b9'
down_revision: Union[str, None] = 'c1d9f6a4b8e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("automation_dispatch_status", sa.String(length=20), nullable=False, server_default="pending"),
    )


def downgrade() -> None:
    op.drop_column("leads", "automation_dispatch_status")
