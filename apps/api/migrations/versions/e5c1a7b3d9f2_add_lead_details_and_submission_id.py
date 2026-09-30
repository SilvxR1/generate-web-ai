"""add lead details and client submission id (H1.2)

A site form's additional fields (`details`, bounded JSON list of
{key, label, value}) and a client-generated submission id that makes a
retried public lead POST idempotent per business. Purely additive: both
columns are nullable (existing rows and every existing caller are
unaffected; NULL ids never conflict under the unique constraint);
downgrade drops only what this revision added.

Revision ID: e5c1a7b3d9f2
Revises: d2b7e4a9c1f3
Create Date: 2026-09-30 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5c1a7b3d9f2'
down_revision: Union[str, None] = 'd2b7e4a9c1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("details", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("client_submission_id", sa.Uuid(), nullable=True))
        batch_op.create_unique_constraint("uq_leads_business_submission", ["business_id", "client_submission_id"])


def downgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_constraint("uq_leads_business_submission", type_="unique")
        batch_op.drop_column("client_submission_id")
        batch_op.drop_column("details")
