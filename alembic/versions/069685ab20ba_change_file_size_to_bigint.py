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
    op.alter_column(
        "videos",
        "upload_file_size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "videos",
        "file_size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "clips",
        "asset_size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "clips",
        "file_size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "publish_jobs",
        "asset_size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "videos",
        "upload_file_size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "videos",
        "file_size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "clips",
        "asset_size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "clips",
        "file_size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "publish_jobs",
        "asset_size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
