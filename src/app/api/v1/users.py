from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import User
from app.schemas import UserCreate, UserRead

router = APIRouter()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_scope() as s:
        yield s


@router.get("/", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[User]:
    rows = (await db.execute(select(User))).scalars().all()
    return cast(list[User], rows)


@router.post("/", response_model=UserRead, status_code=201)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    exists = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "Email already in use")
    obj = User(email=payload.email, full_name=payload.full_name)
    db.add(obj)
    await db.flush()
    return obj
