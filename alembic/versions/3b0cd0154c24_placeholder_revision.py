"""Placeholder revision to satisfy legacy 3b0cd0154c24 dependency.

This revision previously existed in older environments. The schema changes
were folded into adjacent migrations, but deployed databases still reference
the revision ID. Keeping this empty migration preserves the revision chain
so Alembic can continue upgrading.

Revision ID: 3b0cd0154c24
Revises: 97071cd8c877
Create Date: 2025-11-09 02:40:00.000000
"""

revision = "3b0cd0154c24"
down_revision = "97071cd8c877"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op placeholder."""
    pass


def downgrade() -> None:
    """No-op placeholder."""
    pass
