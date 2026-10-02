"""r5.2 supervised import events and preview form signal

R5.2 pre-client hardening:

- source_import_events: append-only lifecycle events on a supervised import
  (an operator discarding a wrong/superseded import). The import, its
  immutable snapshot and its review decisions are never deleted.
- website_drafts.preview_form_submissions / preview_form_last_at: a
  privacy-safe count and time of form submissions that reached the API from
  the draft's Private Preview (nothing else about them is stored).

Purely additive: one new table; the new draft columns are a counter with a
server default of 0 and a nullable timestamp. `source_imports.status` is a
string column, so the new "discarded" value needs no schema change.
Downgrade drops only what this revision added.

Revision ID: b8e2f4a6c1d3
Revises: a7d3f1c5e8b2
Create Date: 2026-10-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e2f4a6c1d3'
down_revision: Union[str, None] = 'a7d3f1c5e8b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_import_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_import_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_import_id"], ["source_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("source_import_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_source_import_events_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_import_events_source_import_id"), ["source_import_id"], unique=False)

    with op.batch_alter_table("website_drafts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("preview_form_submissions", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("preview_form_last_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("website_drafts", schema=None) as batch_op:
        batch_op.drop_column("preview_form_last_at")
        batch_op.drop_column("preview_form_submissions")
    with op.batch_alter_table("source_import_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_import_events_source_import_id"))
        batch_op.drop_index(batch_op.f("ix_source_import_events_tenant_id"))
    op.drop_table("source_import_events")
