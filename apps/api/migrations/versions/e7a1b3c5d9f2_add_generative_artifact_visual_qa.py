"""add generative_website_artifacts.visual_qa_state/screenshot_keys (P2 Visual QA V1)

Revision ID: e7a1b3c5d9f2
Revises: d2e4f8a1c6b9
Create Date: 2026-09-12 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a1b3c5d9f2'
down_revision: Union[str, None] = 'd2e4f8a1c6b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generative_website_artifacts",
        sa.Column("visual_qa_state", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "generative_website_artifacts",
        sa.Column("screenshot_keys", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("generative_website_artifacts", "screenshot_keys")
    op.drop_column("generative_website_artifacts", "visual_qa_state")
