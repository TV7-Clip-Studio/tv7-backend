"""add clip generation mode to videos

Revision ID: 9dbf5c0a9b1d
Revises: b1cb0dcc3961
Create Date: 2025-11-09 14:20:00.000000
"""

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "9dbf5c0a9b1d"
down_revision = "b1cb0dcc3961"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column(
            "clip_generation_mode",
            sa.String(length=16),
            nullable=False,
            server_default="replace",
        ),
    )
    op.execute(
        "UPDATE videos SET clip_generation_mode = 'replace' WHERE clip_generation_mode IS NULL"
    )
    with op.batch_alter_table("videos") as batch:
        batch.alter_column("clip_generation_mode", server_default="replace")


def downgrade() -> None:
    op.drop_column("videos", "clip_generation_mode")
