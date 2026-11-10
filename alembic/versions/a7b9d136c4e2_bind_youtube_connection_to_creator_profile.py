"""Bind the current YouTube connection to one creator profile.

Revision ID: a7b9d136c4e2
Revises: 6e04f43d2a91
"""

import sqlalchemy as sa
from alembic import op

revision = "a7b9d136c4e2"
down_revision = "6e04f43d2a91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("youtube_credentials") as batch:
        batch.add_column(sa.Column("creator_profile_id", sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("youtube_credentials") as batch:
        batch.drop_column("creator_profile_id")
