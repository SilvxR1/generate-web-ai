"""add website draft artifact identity + version traceability (A8.3.4.1)

Build once / promote: a WebsiteDraft now records the storage key and
canonical SHA-256 of the exact validated artifact Publish deploys, and a
WebsiteVersion records which draft (and which artifact hash) it was
promoted from. Purely additive: every column is nullable, no backfill —
existing drafts stay artifact-less (legacy; Publish refuses them and asks
for a new proposal) and existing versions stay untraced. Downgrade drops
only these columns.

Revision ID: d5e8f3a1b2c4
Revises: c4d7e2a9f1b3
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e8f3a1b2c4'
down_revision: Union[str, None] = 'c4d7e2a9f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("website_drafts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("artifact_key", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("artifact_sha256", sa.String(length=64), nullable=True))

    with op.batch_alter_table("website_versions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_website_draft_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("artifact_sha256", sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_website_versions_source_website_draft_id"), ["source_website_draft_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_website_versions_source_website_draft_id_website_drafts",
            "website_drafts",
            ["source_website_draft_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("website_versions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_website_versions_source_website_draft_id_website_drafts", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_website_versions_source_website_draft_id"))
        batch_op.drop_column("artifact_sha256")
        batch_op.drop_column("source_website_draft_id")

    with op.batch_alter_table("website_drafts", schema=None) as batch_op:
        batch_op.drop_column("artifact_sha256")
        batch_op.drop_column("artifact_key")
