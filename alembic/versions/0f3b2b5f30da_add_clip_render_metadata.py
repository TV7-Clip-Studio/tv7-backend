"""add clip render metadata and workspace root

Revision ID: 0f3b2b5f30da
Revises: 9dbf5c0a9b1d
Create Date: 2025-11-08 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "0f3b2b5f30da"
down_revision = "9dbf5c0a9b1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("workspace_root", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "clips",
        sa.Column("render_width", sa.Integer(), nullable=True),
    )
    op.add_column(
        "clips",
        sa.Column("render_height", sa.Integer(), nullable=True),
    )
    op.add_column(
        "clips",
        sa.Column("frame_rate", sa.Float(), nullable=True),
    )
    op.add_column(
        "clips",
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "clips",
        sa.Column("thumbnail_path", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clips", "thumbnail_path")
    op.drop_column("clips", "file_size_bytes")
    op.drop_column("clips", "frame_rate")
    op.drop_column("clips", "render_height")
    op.drop_column("clips", "render_width")
    op.drop_column("videos", "workspace_root")
