from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Generator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import base as db_base
from app.db import models  # noqa: F401  # ensure metadata registration
from app.db.base import Base
from app.main import app


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Provide a dedicated event loop for async tests."""
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Create an in-memory SQLite engine shared across tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Async session factory bound to the shared engine."""
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a database session, rolling back between tests."""
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def configure_app_database(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> AsyncIterator[None]:
    """Route the app's database utilities to the in-memory test engine."""
    if request.node.get_closest_marker("no_db_override"):
        yield
        return

    db_base._engine_factory.cache_clear()
    db_base._session_factory.cache_clear()

    def _create_engine_stub(*_args: Any, **_kwargs: Any) -> AsyncEngine:
        return db_engine

    def _session_factory_stub(*_args: Any, **_kwargs: Any) -> async_sessionmaker[AsyncSession]:
        return session_factory

    monkeypatch.setattr(db_base, "create_async_engine", _create_engine_stub)
    monkeypatch.setattr(db_base, "async_sessionmaker", _session_factory_stub)

    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """HTTP client bound to the FastAPI ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
