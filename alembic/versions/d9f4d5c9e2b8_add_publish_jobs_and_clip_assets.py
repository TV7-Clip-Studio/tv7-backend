"""add publish jobs and clip asset fields

Revision ID: d9f4d5c9e2b8
Revises: cf8f82d9886c
Create Date: 2025-11-21 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "d9f4d5c9e2b8"
down_revision = "cf8f82d9886c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clips") as batch:
        batch.add_column(sa.Column("asset_url", sa.String(length=1024), nullable=True))
        batch.add_column(sa.Column("asset_checksum", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("asset_size_bytes", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "ready_local_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("FALSE"),
            )
        )

    op.create_table(
        "publish_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clip_id", sa.Integer(), sa.ForeignKey("clips.id", ondelete="CASCADE"), index=True
        ),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("asset_url", sa.String(length=1024), nullable=True),
        sa.Column("asset_checksum", sa.String(length=128), nullable=True),
        sa.Column("asset_size_bytes", sa.Integer(), nullable=True),
        sa.Column("response_payload", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("publish_jobs")
    with op.batch_alter_table("clips") as batch:
        batch.drop_column("ready_local_only")
        batch.drop_column("asset_size_bytes")
        batch.drop_column("asset_checksum")
        batch.drop_column("asset_url")
