"""Allow multiple YouTube channels per user and bind OAuth state to a profile.

Revision ID: c2e9f41a0b73
Revises: a7b9d136c4e2
"""

import sqlalchemy as sa
from alembic import op

revision = "c2e9f41a0b73"
down_revision = "a7b9d136c4e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uniques = sa.inspect(op.get_bind()).get_unique_constraints("youtube_credentials")
    user_unique = next(item for item in uniques if item["column_names"] == ["user_id"])
    with op.batch_alter_table(
        "youtube_credentials",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch:
        batch.drop_constraint(
            user_unique["name"] or "uq_youtube_credentials_user_id", type_="unique"
        )
        batch.create_index("ix_youtube_credentials_user_id", ["user_id"])
    with op.batch_alter_table("youtube_oauth_states") as batch:
        batch.add_column(sa.Column("creator_profile_id", sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("youtube_oauth_states") as batch:
        batch.drop_column("creator_profile_id")
    with op.batch_alter_table("youtube_credentials") as batch:
        batch.drop_index("ix_youtube_credentials_user_id")
        batch.create_unique_constraint("uq_youtube_credentials_user_id", ["user_id"])
