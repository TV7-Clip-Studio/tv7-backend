"""add video download fields

Revision ID: 2a3b4c5d6e7f
Revises: 1c6c4f5cb4d1
Create Date: 2025-11-04 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "2a3b4c5d6e7f"
down_revision = "1c6c4f5cb4d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make migration idempotent by checking if columns exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("videos")]

    if "duration_seconds" not in columns:
        op.add_column("videos", sa.Column("duration_seconds", sa.Integer(), nullable=True))
    if "file_size_bytes" not in columns:
        op.add_column("videos", sa.Column("file_size_bytes", sa.Integer(), nullable=True))
    if "error_message" not in columns:
        op.add_column("videos", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "error_message")
    op.drop_column("videos", "file_size_bytes")
    op.drop_column("videos", "duration_seconds")
