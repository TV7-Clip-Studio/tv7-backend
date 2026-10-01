"""Add lease, retry, and provider receipt state to publish jobs.

Revision ID: a12d44e96350
Revises: 8f0d4a6b2c91
"""

import sqlalchemy as sa
from alembic import op

revision = "a12d44e96350"
down_revision = "8f0d4a6b2c91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch:
        batch.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_error_code", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("remote_post_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_publish_jobs_next_attempt_at", ["next_attempt_at"])
        batch.create_index("ix_publish_jobs_lease_expires_at", ["lease_expires_at"])


def downgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch:
        batch.drop_index("ix_publish_jobs_lease_expires_at")
        batch.drop_index("ix_publish_jobs_next_attempt_at")
        for name in (
            "published_at",
            "remote_post_id",
            "last_error_code",
            "lease_expires_at",
            "lease_token",
            "next_attempt_at",
            "attempt_count",
        ):
            batch.drop_column(name)
