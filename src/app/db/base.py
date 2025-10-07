from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""


@lru_cache
def _engine_factory() -> AsyncEngine:
    return create_async_engine(
        str(settings.DATABASE_URL),
        echo=False,
        pool_pre_ping=True,
    )


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=_engine_factory(), expire_on_commit=False)


def get_engine() -> AsyncEngine:
    return _engine_factory()


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return _session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency to yield an async session."""
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        try:
            yield session
        finally:
            # session context manager handles close
            pass


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Async transactional scope for database operations."""
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
