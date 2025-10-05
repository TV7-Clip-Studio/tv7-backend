from __future__ import annotations
from contextlib import asynccontextmanager
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

class Base(DeclarativeBase): pass

_engine: AsyncEngine | None = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None

def get_engine() -> AsyncEngine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_async_engine(str(settings.DATABASE_URL), echo=False, pool_pre_ping=True)
        _SessionLocal = async_sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine

def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _SessionLocal
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal

@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
