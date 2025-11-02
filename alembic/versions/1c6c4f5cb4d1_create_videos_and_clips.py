"""create videos and clips tables

Revision ID: 1c6c4f5cb4d1
Revises: b8ab13ac8612
Create Date: 2025-11-02 02:19:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "1c6c4f5cb4d1"
down_revision = "b8ab13ac8612"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_url", sa.String(length=512), nullable=False),
        sa.Column("local_path", sa.String(length=1024), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="ingested",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_videos_status", "videos", ["status"])

    op.create_table(
        "clips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("start_sec", sa.Integer(), nullable=False),
        sa.Column("end_sec", sa.Integer(), nullable=False),
        sa.Column("local_path", sa.String(length=1024), nullable=True),
        sa.Column("caption_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="rendering",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_clips_status", "clips", ["status"])
    op.create_index("ix_clips_video_id", "clips", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_clips_video_id", table_name="clips")
    op.drop_index("ix_clips_status", table_name="clips")
    op.drop_table("clips")
    op.drop_index("ix_videos_status", table_name="videos")
    op.drop_table("videos")
