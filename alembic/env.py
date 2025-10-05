from __future__ import annotations
from logging.config import fileConfig
from sqlalchemy import pool, create_engine
from alembic import context
from app.db.base import Base
from app.db.models import *  # noqa
from app.core.config import settings

config = context.config

# Only load logging config if INI has logging sections
if config.config_file_name is not None and config.get_section("loggers"):
    try:
        fileConfig(config.config_file_name)  # type: ignore[arg-type]
    except Exception:
        pass

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = str(settings.DATABASE_URL).replace("+asyncpg", "+psycopg")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    sync_url = str(settings.DATABASE_URL).replace("+asyncpg", "+psycopg")
    connectable = create_engine(sync_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
