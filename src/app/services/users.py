from __future__ import annotations

from app.core.security import hash_password, verify_password
from app.db.models import User
from app.repositories.users import UserRepository
from app.schemas import UserCreate, UserUpdate


class UserAlreadyExistsError(Exception):
    """Raised when attempting to create a user with a duplicate email."""


class InvalidPasswordError(Exception):
    """Raised when the provided current password is incorrect."""


class EmailAlreadyTakenError(Exception):
    """Raised when attempting to update to an email that is already in use."""


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


async def get_user_profile(user_id: int, repo: UserRepository) -> User | None:
    """Fetch user profile by ID."""
    return await repo.get_by_id(user_id)


async def update_user_profile(
    user_id: int, updates: UserUpdate, repo: UserRepository
) -> User:
    """
    Update user profile with validation.

    Raises:
        InvalidPasswordError: If current_password is incorrect when changing password.
        EmailAlreadyTakenError: If the new email is already in use by another user.
    """
    user = await repo.get_by_id(user_id)
    if not user:
        raise ValueError("User not found")

    # Handle email update with uniqueness check
    if updates.email and updates.email != user.email:
        existing_user = await repo.get_by_email(updates.email)
        if existing_user and existing_user.id != user_id:
            raise EmailAlreadyTakenError("Email already in use")
        user.email = updates.email

    # Handle full name update
    if updates.full_name:
        user.full_name = updates.full_name

    # Handle password change with verification
    if updates.new_password:
        if not updates.current_password:
            raise InvalidPasswordError("Current password is required to change password")
        if not verify_password(updates.current_password, user.password_hash):
            raise InvalidPasswordError("Current password is incorrect")
        user.password_hash = hash_password(updates.new_password)

    return await repo.update(user)
