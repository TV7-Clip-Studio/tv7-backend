from __future__ import annotations

from contextlib import AbstractContextManager, suppress
from logging.config import fileConfig
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import pool
from sqlalchemy.engine import URL, make_url

from app.core.config import settings

# Import your Base and settings from the app
from app.db.models import Base  # ensure this points to where your models' metadata lives

if TYPE_CHECKING:
    from alembic.config import Config

    class AlembicContext(Protocol):
        config: Config

        def begin_transaction(self) -> AbstractContextManager[None]: ...

        def configure(self, *args: Any, **kwargs: Any) -> None: ...

        def run_migrations(self) -> None: ...

        def is_offline_mode(self) -> bool: ...

    context: AlembicContext
else:
    from alembic import context  # type: ignore[attr-defined]

# this is the Alembic Config object, which provides access to the values within the .ini file.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None and config.get_section("loggers"):
    with suppress(Exception):
        fileConfig(config.config_file_name)  # type: ignore[arg-type]

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def _sync_url_from_async(async_url: str | URL) -> str:
    """
    Alembic's engine is synchronous. Convert an async driver URL (e.g., postgresql+asyncpg)
    to a sync one (postgresql+psycopg).
    """
    url = make_url(async_url)
    # Normalize to psycopg (v3) sync driver
    url = url.set(drivername="postgresql+psycopg")
    return str(url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    async_url = settings.DATABASE_URL
    sync_url = _sync_url_from_async(async_url)

    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    async_url = settings.DATABASE_URL
    sync_url = _sync_url_from_async(async_url)

    connectable = create_sync_engine(sync_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
