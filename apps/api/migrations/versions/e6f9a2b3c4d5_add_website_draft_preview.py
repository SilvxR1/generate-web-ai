"""add website draft preview metadata (A8.3.4.2a)

Real draft preview: a WebsiteDraft records its current preview deployment
(id, URL, creation time) in the dedicated preview Pages project. Purely
additive: nullable, no backfill; expiry is derived from preview_created_at.
Downgrade drops only these columns.

Revision ID: e6f9a2b3c4d5
Revises: d5e8f3a1b2c4
Create Date: 2026-09-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f9a2b3c4d5'
down_revision: Union[str, None] = 'd5e8f3a1b2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("website_drafts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("preview_deployment_id", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("preview_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(sa.Column("preview_created_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("website_drafts", schema=None) as batch_op:
        batch_op.drop_column("preview_created_at")
        batch_op.drop_column("preview_url")
        batch_op.drop_column("preview_deployment_id")
