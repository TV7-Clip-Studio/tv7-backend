"""Placeholder migration to preserve the expected revision chain.

Revision ID: b8ab13ac8612
Revises: fd1f093acad5
Create Date: 2025-10-03 12:28:28.466082
"""

revision = "b8ab13ac8612"
down_revision = "fd1f093acad5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No schema changes required; revision maintained for compatibility.
    pass


def downgrade() -> None:
    # No schema changes introduced in this revision.
    pass
