"""add website version artifact provenance (v0.2 S1)

Artifact-backed exact rollback: a WebsiteVersion records the private
storage key of the exact artifact it deployed (so it can be restored
without depending on its source WebsiteDraft), and a rollback deployment
records which historical version it restored. Purely additive: nullable,
no backfill — historical rows are never given provenance they did not
record. Downgrade drops only these columns.

Revision ID: f1a7c3e9b2d4
Revises: e6f9a2b3c4d5
Create Date: 2026-09-29 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a7c3e9b2d4'
down_revision: Union[str, None] = 'e6f9a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("website_versions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("artifact_key", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("rolled_back_from_version_id", sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_website_versions_rolled_back_from_version_id"), ["rolled_back_from_version_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_website_versions_rolled_back_from_version_id",
            "website_versions",
            ["rolled_back_from_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("website_versions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_website_versions_rolled_back_from_version_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_website_versions_rolled_back_from_version_id"))
        batch_op.drop_column("rolled_back_from_version_id")
        batch_op.drop_column("artifact_key")
