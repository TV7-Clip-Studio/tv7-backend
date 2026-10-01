"""Add encrypted YouTube OAuth and resumable upload state.

Revision ID: c7d4e2b9a610
Revises: b457e9c83a12
"""

import sqlalchemy as sa
from alembic import op

revision = "c7d4e2b9a610"
down_revision = "b457e9c83a12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("youtube_credentials") as batch:
        batch.add_column(
            sa.Column("token_encryption_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("channel_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("channel_title", sa.String(length=255), nullable=True))
        batch.create_unique_constraint("uq_youtube_credentials_channel_id", ["channel_id"])
    with op.batch_alter_table("publish_jobs") as batch:
        batch.add_column(sa.Column("provider_upload_uri_encrypted", sa.Text(), nullable=True))
    op.create_table(
        "youtube_oauth_states",
        sa.Column("state_hash", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("youtube_oauth_states")
    with op.batch_alter_table("publish_jobs") as batch:
        batch.drop_column("provider_upload_uri_encrypted")
    with op.batch_alter_table("youtube_credentials") as batch:
        batch.drop_constraint("uq_youtube_credentials_channel_id", type_="unique")
        batch.drop_column("channel_title")
        batch.drop_column("channel_id")
        batch.drop_column("token_encryption_version")
