from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.db.base as db_base_module
import app.db.models as models_module
from app.db.models import User

PatchedBase = tuple[ModuleType, async_sessionmaker[AsyncSession], type[User]]


@pytest_asyncio.fixture
async def patched_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[PatchedBase]:
    db_base = importlib.reload(db_base_module)
    models_mod = importlib.reload(models_module)
    user_model = models_mod.User

    db_path = tmp_path / "app.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    db_base._engine_factory.cache_clear()
    db_base._session_factory.cache_clear()

    def _create_engine_stub(*_args: Any, **_kwargs: Any) -> AsyncEngine:
        return engine

    def _session_factory_stub(*_args: Any, **_kwargs: Any) -> async_sessionmaker[AsyncSession]:
        return session_factory

    monkeypatch.setattr(db_base, "create_async_engine", _create_engine_stub)
    monkeypatch.setattr(db_base, "async_sessionmaker", _session_factory_stub)

    async with engine.begin() as conn:
        await conn.run_sync(db_base.Base.metadata.create_all)

    try:
        yield db_base, session_factory, user_model
    finally:
        await engine.dispose()


@pytest.mark.no_db_override
@pytest.mark.asyncio
async def test_session_scope_commit(patched_base: PatchedBase) -> None:
    db_base, session_factory, user_model = patched_base

    async with db_base.session_scope() as session:
        session.add(
            user_model(
                email="commit@example.com",
                full_name="Commit User",
                password_hash="hashed-secret",
            )
        )

    async with session_factory() as session:
        rows = (await session.execute(select(user_model))).scalars().all()
        assert any(row.email == "commit@example.com" for row in rows)


@pytest.mark.no_db_override
@pytest.mark.asyncio
async def test_session_scope_rollback(patched_base: PatchedBase) -> None:
    db_base, session_factory, user_model = patched_base

    with pytest.raises(RuntimeError):
        async with db_base.session_scope() as session:
            session.add(
                user_model(
                    email="rollback@example.com",
                    full_name="Rollback User",
                    password_hash="hashed-secret",
                )
            )
            raise RuntimeError("trigger rollback")

    async with session_factory() as session:
        rows = (await session.execute(select(user_model))).scalars().all()
        assert all(row.email != "rollback@example.com" for row in rows)


@pytest.mark.no_db_override
@pytest.mark.asyncio
async def test_get_db_generator(patched_base: PatchedBase) -> None:
    db_base, _, _ = patched_base

    generator = db_base.get_db()
    session = await anext(generator)
    assert isinstance(session, AsyncSession)

    await generator.aclose()
