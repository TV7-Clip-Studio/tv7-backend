"""Prevent concurrent duplicate uploads of the same render to a destination."""

from alembic import op

revision = "f5a8b21c670d"
down_revision = "e4b7c91fd205"
branch_labels = None
depends_on = None

COLUMNS = [
    "user_id",
    "creator_profile_id",
    "target_account_ref",
    "checksum_sha256",
    "size_bytes",
    "content_type",
]


def upgrade() -> None:
    # Existing duplicates fail migration for explicit review; provider receipts
    # must never be silently removed.
    op.create_index("uq_local_youtube_render_target", "local_youtube_uploads", COLUMNS, unique=True)


def downgrade() -> None:
    op.drop_index("uq_local_youtube_render_target", table_name="local_youtube_uploads")
