"""p1 lead deletion events

P1 lead retention and deletion:

- lead_deletion_events: append-only record that a lead was deleted (by an
  operator, e.g. an erasure request, or by the retention job) — who/what,
  when, why, and how many notes/notifications went with it. It keeps none
  of the visitor's personal data; `lead_id` is no foreign key (the lead is
  gone) and is unique per business so a retried deletion is a no-op.

Purely additive: one new table. The retention period itself lives in the
business's JSON config (lead_management.retention_days), so it needs no
schema change. Downgrade drops only what this revision added.

Revision ID: c4d9e2a7f1b3
Revises: b8e2f4a6c1d3
Create Date: 2026-10-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d9e2a7f1b3'
down_revision: Union[str, None] = 'b8e2f4a6c1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_deletion_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=True),
        sa.Column("lead_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes_deleted", sa.Integer(), nullable=False),
        sa.Column("notifications_deleted", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "lead_id", name="uq_lead_deletion_events_business_lead"),
    )
    with op.batch_alter_table("lead_deletion_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_lead_deletion_events_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_lead_deletion_events_business_id"), ["business_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("lead_deletion_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lead_deletion_events_business_id"))
        batch_op.drop_index(batch_op.f("ix_lead_deletion_events_tenant_id"))
    op.drop_table("lead_deletion_events")
