"""Add encrypted Instagram and TikTok profile connections.

Revision ID: d3f8a12bc904
Revises: c2e9f41a0b73
"""

import sqlalchemy as sa
from alembic import op

revision = "d3f8a12bc904"
down_revision = "c2e9f41a0b73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "social_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("provider_account_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("creator_profile_id", sa.String(80), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("platform", "provider_account_id"),
    )
    op.create_index("ix_social_credentials_user_id", "social_credentials", ["user_id"])
    op.create_table(
        "social_oauth_states",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("creator_profile_id", sa.String(80), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("social_oauth_states")
    op.drop_index("ix_social_credentials_user_id", table_name="social_credentials")
    op.drop_table("social_credentials")
