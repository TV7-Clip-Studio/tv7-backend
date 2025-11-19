"""add upload ingest support fields

Revision ID: cf8f82d9886c
Revises: 6b8c396d5d8a
Create Date: 2025-11-15 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "cf8f82d9886c"
down_revision = "6b8c396d5d8a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("videos") as batch:
        batch.add_column(
            sa.Column(
                "ingest_type",
                sa.String(length=32),
                nullable=False,
                server_default="youtube",
            )
        )
        batch.add_column(sa.Column("original_filename", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("upload_checksum", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("upload_file_size_bytes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("upload_original_path", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("videos") as batch:
        batch.drop_column("upload_original_path")
        batch.drop_column("upload_file_size_bytes")
        batch.drop_column("upload_checksum")
        batch.drop_column("original_filename")
        batch.drop_column("ingest_type")
