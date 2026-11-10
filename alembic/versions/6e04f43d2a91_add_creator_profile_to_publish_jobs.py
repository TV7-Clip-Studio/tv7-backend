"""Bind schedule drafts to the local creator profile that created them.

Revision ID: 6e04f43d2a91
Revises: d8e5f3a1b720
"""

import sqlalchemy as sa
from alembic import op

revision = "6e04f43d2a91"
down_revision = "d8e5f3a1b720"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch:
        batch.add_column(sa.Column("creator_profile_id", sa.String(length=80), nullable=True))
        batch.create_index("ix_publish_jobs_creator_profile_id", ["creator_profile_id"])


def downgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch:
        batch.drop_index("ix_publish_jobs_creator_profile_id")
        batch.drop_column("creator_profile_id")
