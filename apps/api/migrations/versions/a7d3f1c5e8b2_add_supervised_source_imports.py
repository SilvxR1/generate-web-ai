"""add supervised source imports (R5)

Operator-imported, owner-reviewed website exports (Higgsfield) and the
audited human decisions on their review findings; the job kind / trust
class / plan identity a source-adaptation job carries; and the exact
artifact identity a draft approval binds to.

Purely additive: two new tables; new generation_jobs columns have server
defaults matching every existing row (generative, untrusted_generated);
nullable columns everywhere else. Downgrade drops only what this revision
added.

Revision ID: a7d3f1c5e8b2
Revises: e5c1a7b3d9f2
Create Date: 2026-09-30 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3f1c5e8b2'
down_revision: Union[str, None] = 'e5c1a7b3d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("zip_sha256", sa.String(length=64), nullable=False),
        sa.Column("zip_size", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_key", sa.String(length=512), nullable=False),
        sa.Column("source_family", sa.String(length=64), nullable=True),
        sa.Column("adapter_id", sa.String(length=100), nullable=True),
        sa.Column("adapter_version", sa.String(length=20), nullable=True),
        sa.Column("adapter_contract_version", sa.String(length=20), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("manifest_key", sa.String(length=512), nullable=True),
        sa.Column("supportability", sa.String(length=40), nullable=True),
        sa.Column("plan_sha256", sa.String(length=64), nullable=True),
        sa.Column("plan_key", sa.String(length=512), nullable=True),
        sa.Column("business_truth_sha256", sa.String(length=64), nullable=True),
        sa.Column("site_origin", sa.String(length=2048), nullable=False),
        sa.Column("api_base_url", sa.String(length=2048), nullable=False),
        sa.Column("inspection", sa.JSON(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("draft_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["generation_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["draft_id"], ["website_drafts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("source_imports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_source_imports_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_imports_business_id"), ["business_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_imports_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_imports_zip_sha256"), ["zip_sha256"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_imports_draft_id"), ["draft_id"], unique=False)

    op.create_table(
        "source_review_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_import_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.String(length=400), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_import_id"], ["source_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("source_review_decisions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_source_review_decisions_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_source_review_decisions_source_import_id"), ["source_import_id"], unique=False
        )

    with op.batch_alter_table("generation_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("job_kind", sa.String(length=30), server_default="generative", nullable=False))
        batch_op.add_column(
            sa.Column("trust_class", sa.String(length=30), server_default="untrusted_generated", nullable=False)
        )
        batch_op.add_column(sa.Column("plan_sha256", sa.String(length=64), nullable=True))

    with op.batch_alter_table("website_drafts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("approved_artifact_sha256", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("website_drafts", schema=None) as batch_op:
        batch_op.drop_column("approved_artifact_sha256")
    with op.batch_alter_table("generation_jobs", schema=None) as batch_op:
        batch_op.drop_column("plan_sha256")
        batch_op.drop_column("trust_class")
        batch_op.drop_column("job_kind")
    with op.batch_alter_table("source_review_decisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_review_decisions_source_import_id"))
        batch_op.drop_index(batch_op.f("ix_source_review_decisions_tenant_id"))
    op.drop_table("source_review_decisions")
    with op.batch_alter_table("source_imports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_imports_draft_id"))
        batch_op.drop_index(batch_op.f("ix_source_imports_zip_sha256"))
        batch_op.drop_index(batch_op.f("ix_source_imports_status"))
        batch_op.drop_index(batch_op.f("ix_source_imports_business_id"))
        batch_op.drop_index(batch_op.f("ix_source_imports_tenant_id"))
    op.drop_table("source_imports")
