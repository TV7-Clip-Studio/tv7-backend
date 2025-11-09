"""add oauth accounts table and provider metadata

Revision ID: 3b0cd0154c24
Revises: 97071cd8c877
Create Date: 2025-11-07 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "3b0cd0154c24"
down_revision = "97071cd8c877"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "primary_auth_provider",
            sa.String(length=32),
            nullable=False,
            server_default="email",
        ),
    )
    op.execute("UPDATE users SET primary_auth_provider='email'")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)

    op.create_table(
        "user_oauth_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("picture_url", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_provider"),
    )
    op.create_index(
        op.f("ix_user_oauth_accounts_user_id"), "user_oauth_accounts", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_oauth_accounts_provider"), "user_oauth_accounts", ["provider"], unique=False
    )
    op.create_index(
        op.f("ix_user_oauth_accounts_provider_user_id"),
        "user_oauth_accounts",
        ["provider_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_oauth_accounts_provider_user_id"), table_name="user_oauth_accounts")
    op.drop_index(op.f("ix_user_oauth_accounts_provider"), table_name="user_oauth_accounts")
    op.drop_index(op.f("ix_user_oauth_accounts_user_id"), table_name="user_oauth_accounts")
    op.drop_table("user_oauth_accounts")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("users", "primary_auth_provider")
