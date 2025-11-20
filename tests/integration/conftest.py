from __future__ import annotations

# ruff: noqa: PLC0415
import os
import sys
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from importlib import reload
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio
from alembic import command as alembic_command  # type: ignore[attr-defined]
from alembic.config import Config
from asgi_lifespan import LifespanManager
from docker.errors import DockerException
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url
from testcontainers.postgres import PostgresContainer

from app.core.security import hash_password
from app.db import models  # noqa: F401  # ensure all models are registered
from app.db.base import get_sessionmaker
from app.db.models import User

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

_DOCKER_SOCKET_CANDIDATES = (
    Path.home() / ".docker/run/docker.sock",
    Path.home() / "Library/Containers/com.docker.docker/Data/docker.sock",
    Path.home() / "Library/Containers/com.docker.docker/Data/docker-cli.sock",
)


@dataclass(frozen=True, slots=True)
class DatabaseURLs:
    sync: str
    async_: str


def _as_async_url(url: str) -> str:
    parsed: URL = make_url(url)
    return cast(
        str,
        parsed.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False),
    )


def _as_sync_url(url: str) -> str:
    parsed: URL = make_url(url)
    return cast(
        str,
        parsed.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
    )


def _run_migrations(sync_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url)
    alembic_command.upgrade(config, "head")


def _fallback_database_urls() -> DatabaseURLs:
    async_url = os.getenv("TEST_DATABASE_URL")
    if async_url is None:
        pytest.skip(
            "Docker is unavailable and TEST_DATABASE_URL is not set; " "skipping integration tests."
        )

    async_url_str = str(async_url)
    sync_url = _as_sync_url(async_url_str)
    _run_migrations(sync_url)
    return DatabaseURLs(sync=sync_url, async_=async_url_str)


@pytest.fixture(scope="session")
def database_urls() -> Iterator[DatabaseURLs]:
    override = os.getenv("TEST_DATABASE_URL")
    if override:
        urls = _fallback_database_urls()
        yield urls
        return

    image = os.getenv("TEST_POSTGRES_IMAGE", "postgres:16-alpine")
    if (
        "DOCKER_HOST" not in os.environ and sys.platform == "darwin"
    ):  # pragma: no cover - platform specific
        for candidate in _DOCKER_SOCKET_CANDIDATES:
            if candidate.exists():
                os.environ["DOCKER_HOST"] = f"unix://{candidate}"
                break

    try:
        container = PostgresContainer(
            image,
            username="postgres",
            password="postgres",
            dbname="appdb",
        )
        container.start()
    except DockerException:
        yield _fallback_database_urls()
        return

    try:
        connection_url = container.get_connection_url()
        sync_url = _as_sync_url(connection_url)
        async_url = _as_async_url(connection_url)
        try:
            _run_migrations(sync_url)
        except Exception:
            container.stop()
            yield _fallback_database_urls()
            return

        yield DatabaseURLs(sync=sync_url, async_=async_url)
    finally:
        container.stop()


@pytest.fixture(scope="session")
def app_with_db(database_urls: DatabaseURLs) -> Iterator[FastAPI]:
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_urls.async_

    import app.core.config as config_module  # noqa: E402
    import app.db.base as db_base  # noqa: E402
    import app.db.models as models_module  # noqa: E402
    import app.main as main_module  # noqa: E402

    reload(config_module)
    reload(db_base)
    reload(models_module)
    reload(main_module)

    try:
        yield main_module.app
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url


@pytest_asyncio.fixture
async def async_client(app_with_db: FastAPI) -> AsyncIterator[AsyncClient]:
    async with LifespanManager(app_with_db):
        transport = ASGITransport(app=app_with_db)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest_asyncio.fixture
async def integration_login_credentials() -> AsyncIterator[tuple[str, str]]:
    sessionmaker = get_sessionmaker()
    email = f"integration-{os.urandom(4).hex()}@example.com"
    password = "integration-password"
    async with sessionmaker() as session:
        user = User(
            email=email, full_name="Integration Auth", password_hash=hash_password(password)
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    try:
        yield email, password
    finally:
        async with sessionmaker() as session:
            await session.execute(delete(User).where(User.email == email))
            await session.commit()


@pytest_asyncio.fixture
async def integration_auth_headers(
    async_client: AsyncClient, integration_login_credentials: tuple[str, str]
) -> dict[str, str]:
    email, password = integration_login_credentials
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
