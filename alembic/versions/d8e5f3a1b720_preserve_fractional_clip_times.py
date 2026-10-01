"""Preserve subsecond clip boundaries for rendered media.

Revision ID: d8e5f3a1b720
Revises: c7d4e2b9a610
"""

import sqlalchemy as sa
from alembic import op

revision = "d8e5f3a1b720"
down_revision = "c7d4e2b9a610"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clips") as batch:
        batch.alter_column(
            "start_sec", existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False
        )
        batch.alter_column(
            "end_sec", existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("clips") as batch:
        batch.alter_column(
            "start_sec", existing_type=sa.Float(), type_=sa.Integer(), existing_nullable=False
        )
        batch.alter_column(
            "end_sec", existing_type=sa.Float(), type_=sa.Integer(), existing_nullable=False
        )
