"""Persist local-to-YouTube upload session metadata without media assets."""

import sqlalchemy as sa
from alembic import op

revision = "e4b7c91fd205"
down_revision = "d3f8a12bc904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_youtube_uploads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("creator_profile_id", sa.String(80), nullable=False),
        sa.Column("target_account_ref", sa.String(255), nullable=False),
        sa.Column("local_clip_id", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_upload_uri_encrypted", sa.Text(), nullable=True),
        sa.Column("remote_video_id", sa.String(128), nullable=True),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_local_youtube_owner_key"),
    )
    op.create_index("ix_local_youtube_uploads_user_id", "local_youtube_uploads", ["user_id"])
    op.create_index(
        "ix_local_youtube_uploads_creator_profile_id",
        "local_youtube_uploads",
        ["creator_profile_id"],
    )


def downgrade() -> None:
    op.drop_table("local_youtube_uploads")
