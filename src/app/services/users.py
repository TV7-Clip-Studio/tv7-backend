from __future__ import annotations

from app.core.security import hash_password
from app.db.models import User
from app.repositories.users import UserRepository
from app.schemas import UserCreate


class UserAlreadyExistsError(Exception):
    """Raised when attempting to create a user with a duplicate email."""


async def list_users(repo: UserRepository) -> list[User]:
    return await repo.list_users()


async def create_user(payload: UserCreate, repo: UserRepository) -> User:
    if await repo.get_by_email(payload.email):
        raise UserAlreadyExistsError("Email already in use")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
    )
    await repo.add(user)
    return await repo.refresh(user)
