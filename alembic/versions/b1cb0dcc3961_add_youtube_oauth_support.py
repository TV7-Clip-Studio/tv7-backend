"""add youtube oauth support

Revision ID: b1cb0dcc3961
Revises: 3b0cd0154c24
Create Date: 2025-11-08 21:40:43.537208
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "b1cb0dcc3961"
down_revision = "3b0cd0154c24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make migration idempotent by checking if columns/tables exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Check if requested_by_user_id column exists
    columns = [col["name"] for col in inspector.get_columns("videos")]
    if "requested_by_user_id" not in columns:
        op.add_column(
            "videos",
            sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_videos_requested_by_user_id",
            "videos",
            "users",
            ["requested_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_videos_requested_by_user_id", "videos", ["requested_by_user_id"])

    # Check if youtube_credentials table exists
    tables = inspector.get_table_names()
    if "youtube_credentials" not in tables:
        op.create_table(
            "youtube_credentials",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("access_token", sa.String(length=2048), nullable=False),
            sa.Column("refresh_token", sa.String(length=2048), nullable=False),
            sa.Column("token_type", sa.String(length=64), nullable=True),
            sa.Column("scope", sa.String(length=512), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
                server_onupdate=sa.func.now(),
            ),
        )


def downgrade() -> None:
    op.drop_table("youtube_credentials")
    op.drop_index("ix_videos_requested_by_user_id", table_name="videos")
    op.drop_constraint("fk_videos_requested_by_user_id", "videos", type_="foreignkey")
    op.drop_column("videos", "requested_by_user_id")
