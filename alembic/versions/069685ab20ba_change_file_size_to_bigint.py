"""change file size to bigint

Revision ID: 069685ab20ba
Revises: d9f4d5c9e2b8
Create Date: 2025-11-24 22:47:55.478971
"""

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

revision = "069685ab20ba"
down_revision = "d9f4d5c9e2b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("videos") as batch_op:
        batch_op.alter_column(
            "upload_file_size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "file_size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )

    with op.batch_alter_table("clips") as batch_op:
        batch_op.alter_column(
            "asset_size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "file_size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )

    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.alter_column(
            "asset_size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("videos") as batch_op:
        batch_op.alter_column(
            "upload_file_size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "file_size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )

    with op.batch_alter_table("clips") as batch_op:
        batch_op.alter_column(
            "asset_size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "file_size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )

    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.alter_column(
            "asset_size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
