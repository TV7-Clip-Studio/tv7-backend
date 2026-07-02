"""add cloud ai credit metering

Revision ID: 4f9d0c6b8a21
Revises: 069685ab20ba
Create Date: 2026-06-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4f9d0c6b8a21"
down_revision: str | None = "069685ab20ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cloud_ai_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("credits_charged", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cloud_ai_requests_user_id"), "cloud_ai_requests", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_cloud_ai_requests_status"), "cloud_ai_requests", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_cloud_ai_requests_error_code"), "cloud_ai_requests", ["error_code"], unique=False
    )

    op.create_table(
        "cloud_ai_credit_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["cloud_ai_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cloud_ai_credit_transactions_user_id"),
        "cloud_ai_credit_transactions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cloud_ai_credit_transactions_kind"),
        "cloud_ai_credit_transactions",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cloud_ai_credit_transactions_request_id"),
        "cloud_ai_credit_transactions",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_cloud_ai_credit_transactions_request_id"),
        table_name="cloud_ai_credit_transactions",
    )
    op.drop_index(
        op.f("ix_cloud_ai_credit_transactions_kind"),
        table_name="cloud_ai_credit_transactions",
    )
    op.drop_index(
        op.f("ix_cloud_ai_credit_transactions_user_id"),
        table_name="cloud_ai_credit_transactions",
    )
    op.drop_table("cloud_ai_credit_transactions")
    op.drop_index(op.f("ix_cloud_ai_requests_error_code"), table_name="cloud_ai_requests")
    op.drop_index(op.f("ix_cloud_ai_requests_status"), table_name="cloud_ai_requests")
    op.drop_index(op.f("ix_cloud_ai_requests_user_id"), table_name="cloud_ai_requests")
    op.drop_table("cloud_ai_requests")
