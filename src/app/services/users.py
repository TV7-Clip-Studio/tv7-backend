from __future__ import annotations

from app.core.security import hash_password
from app.db.models import User
from app.repositories.users import UserRepository
from app.schemas import UserCreate


class UserAlreadyExistsError(Exception):
    """Raised when attempting to create a user with a duplicate email."""


class UserNotFoundError(Exception):
    """Raised when attempting to access a non-existent user."""


class CannotDeleteCurrentUserError(Exception):
    """Raised when attempting to delete the currently logged-in user."""


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


async def get_user_detail(repo: UserRepository, user_id: int) -> User:
    user = await repo.get_by_id(user_id)
    if not user:
        raise UserNotFoundError(f"User with ID {user_id} not found")
    return user


async def update_user_status(user_id: int, is_active: bool, repo: UserRepository) -> User:
    user = await get_user_detail(repo, user_id)
    user.is_active = is_active
    return await repo.update(user)


async def delete_user(
    user_id: int, repo: UserRepository, current_user_id: int | None = None
) -> None:
    if current_user_id and user_id == current_user_id:
        raise CannotDeleteCurrentUserError("Cannot delete the currently logged-in user")

    user = await get_user_detail(repo, user_id)
    await repo.delete(user.id)
