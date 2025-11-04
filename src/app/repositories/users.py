from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    """Persistence helpers for User entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_users(self) -> list[User]:
        result = await self._session.execute(select(User))
        rows: Iterable[User] = result.scalars().all()
        return list(rows)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        user: User | None = result.scalar_one_or_none()
        return user

    async def add(self, user: User) -> None:
        self._session.add(user)

    async def refresh(self, user: User) -> User:
        await self._session.flush()
        await self._session.refresh(user)
        return user
