"""add authentication and tenant access (A2)

Adds the additive schema for server-side session authentication and
explicit many-to-many tenant authorization:

- users: drops the old tenant_id FK/index and its uq_users_tenant_email
  constraint (a User is no longer scoped to exactly one tenant), adds
  hashed_password and a new uq_users_email constraint (email is now
  globally unique across the table, not per-tenant).
- tenant_access: the new join table — one row per (user_id, tenant_id)
  grant, with a per-grant role. Knowing a tenant's UUID never grants
  access; a row here is the only thing that does (see
  app.dependencies.get_current_tenant_id).
- user_sessions: server-side session records. Stores only a SHA-256
  digest of the opaque session token (token_hash), never the raw token,
  plus a per-session CSRF token compared via hmac.compare_digest on
  non-safe-method requests (see app.dependencies._check_csrf).

Deliberately does NOT insert any User row — the real production operator
user is created as an A2 cutover operation, not a schema migration (see
docs/a2-authentication-authorization.md). Existing tenants/businesses/etc.
are untouched.

Revision ID: b1e2f9a08c3d
Revises: 7520645bb2f1
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1e2f9a08c3d'
down_revision: Union[str, None] = '7520645bb2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("hashed_password", sa.String(length=255), nullable=True))
        batch_op.drop_constraint("uq_users_tenant_email", type_="unique")
        batch_op.drop_index(batch_op.f("ix_users_tenant_id"))
        batch_op.drop_column("tenant_id")
        batch_op.drop_column("role")
        batch_op.create_unique_constraint("uq_users_email", ["email"])

    op.create_table(
        "tenant_access",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Enum("owner", "operator", name="userrole", native_enum=False, length=20), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_tenant_access_user_tenant"),
    )
    op.create_index(op.f("ix_tenant_access_user_id"), "tenant_access", ["user_id"], unique=False)
    op.create_index(op.f("ix_tenant_access_tenant_id"), "tenant_access", ["tenant_id"], unique=False)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_sessions_token_hash"), "user_sessions", ["token_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_sessions_token_hash"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index(op.f("ix_tenant_access_tenant_id"), table_name="tenant_access")
    op.drop_index(op.f("ix_tenant_access_user_id"), table_name="tenant_access")
    op.drop_table("tenant_access")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("uq_users_email", type_="unique")
        batch_op.add_column(sa.Column("role", sa.Enum("owner", "operator", name="userrole", native_enum=False, length=20), nullable=False, server_default="operator"))
        # Nullable here (the pre-A2 column was NOT NULL): a downgrade has no
        # way to know which tenant each existing User row "belonged" to, so
        # it cannot backfill a value — this mirrors that data loss is
        # inherent to downgrading past this migration, not a schema bug.
        batch_op.add_column(sa.Column("tenant_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_index(batch_op.f("ix_users_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_unique_constraint("uq_users_tenant_email", ["tenant_id", "email"])
        batch_op.drop_column("hashed_password")
