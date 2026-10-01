"""Add private uploaded assets and durable schedule draft metadata.

Revision ID: 8f0d4a6b2c91
Revises: 4f9d0c6b8a21
"""

import sqlalchemy as sa
from alembic import op

revision = "8f0d4a6b2c91"
down_revision = "4f9d0c6b8a21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uploaded_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_uploaded_assets_user_id", "uploaded_assets", ["user_id"])
    with op.batch_alter_table("publish_jobs") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("asset_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("target_account_ref", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("caption", sa.Text(), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch.create_foreign_key(
            "fk_publish_jobs_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_publish_jobs_asset_id", "uploaded_assets", ["asset_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_publish_jobs_user_id", ["user_id"])
        batch.create_index("ix_publish_jobs_scheduled_at", ["scheduled_at"])
        batch.create_unique_constraint(
            "uq_publish_jobs_user_idempotency", ["user_id", "idempotency_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch:
        batch.drop_constraint("uq_publish_jobs_user_idempotency", type_="unique")
        batch.drop_index("ix_publish_jobs_scheduled_at")
        batch.drop_index("ix_publish_jobs_user_id")
        batch.drop_constraint("fk_publish_jobs_asset_id", type_="foreignkey")
        batch.drop_constraint("fk_publish_jobs_user_id", type_="foreignkey")
        for name in (
            "idempotency_key",
            "caption",
            "target_account_ref",
            "scheduled_at",
            "asset_id",
            "user_id",
        ):
            batch.drop_column(name)
    op.drop_index("ix_uploaded_assets_user_id", table_name="uploaded_assets")
    op.drop_table("uploaded_assets")
