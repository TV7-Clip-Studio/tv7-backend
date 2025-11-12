"""add render batch id to videos

Revision ID: 6b8c396d5d8a
Revises: 0f3b2b5f30da
Create Date: 2025-11-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "6b8c396d5d8a"
down_revision = "0f3b2b5f30da"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("render_batch_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "render_batch_id")
