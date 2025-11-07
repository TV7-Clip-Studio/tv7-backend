"""add transcript language

Revision ID: 97071cd8c877
Revises: 2a3b4c5d6e7f
Create Date: 2025-11-06 21:24:35.883588
"""

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "97071cd8c877"
down_revision = "2a3b4c5d6e7f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("transcript_language", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("videos", "transcript_language")
