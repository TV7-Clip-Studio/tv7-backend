"""Track the storage provider for each approved scheduled asset.

Revision ID: b457e9c83a12
Revises: a12d44e96350
"""

import sqlalchemy as sa
from alembic import op

revision = "b457e9c83a12"
down_revision = "a12d44e96350"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("uploaded_assets") as batch:
        batch.add_column(
            sa.Column("storage_backend", sa.String(length=16), nullable=False, server_default="local")
        )


def downgrade() -> None:
    with op.batch_alter_table("uploaded_assets") as batch:
        batch.drop_column("storage_backend")
