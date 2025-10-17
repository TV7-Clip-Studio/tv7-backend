import os
from contextlib import suppress
from importlib import import_module
from logging.config import fileConfig
from typing import Any, cast

from alembic.config import Config
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from app.db.models import Base

# this is the Alembic Config object, which provides access to the values within the .ini file.
alembic_module = import_module("alembic")
context = cast(Any, alembic_module.context)
config: Config = context.config

# Interpret the config file for Python logging when logging sections exist.
if config.config_file_name is not None and config.get_section("loggers"):
    with suppress(Exception):
        fileConfig(config.config_file_name)

# Add your model's MetaData object here for 'autogenerate' support.
target_metadata = Base.metadata


db_admin_url = os.getenv("DATABASE_ADMIN_URL")
if db_admin_url:
    config.set_main_option("sqlalchemy.url", db_admin_url)
else:
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        config.set_main_option("sqlalchemy.url", db_url)


def _resolve_sqlalchemy_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url or url in {"${DATABASE_ADMIN_URL}", "${DATABASE_URL}"}:
        raise RuntimeError(
            "DATABASE_ADMIN_URL (or fallback DATABASE_URL) is not set for Alembic; "
            "export it before running migrations."
        )

    url_obj = make_url(url)
    if url_obj.database:
        base_dir = os.path.dirname(url_obj.database)
        if base_dir and not os.path.exists(base_dir):
            os.makedirs(base_dir, exist_ok=True)

    driver = url_obj.drivername
    if driver.endswith("+aiosqlite"):
        url_obj = url_obj.set(drivername="sqlite+pysqlite")
    elif driver.endswith("+asyncpg"):
        url_obj = url_obj.set(drivername="postgresql+psycopg")
    elif driver.endswith("+asyncmy"):
        url_obj = url_obj.set(drivername="mysql+pymysql")

    resolved = str(url_obj.render_as_string(hide_password=False))
    config.set_main_option("sqlalchemy.url", resolved)
    return resolved


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _resolve_sqlalchemy_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    _resolve_sqlalchemy_url()

    section = cast(dict[str, Any], config.get_section(config.config_ini_section) or {})

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
