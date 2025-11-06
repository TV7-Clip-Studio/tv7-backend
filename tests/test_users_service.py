"""Tests for user service functions."""

from __future__ import annotations

import pytest

from app.db.models import User
from app.repositories.users import UserRepository
from app.services.users import (
    CannotDeleteCurrentUserError,
    UserNotFoundError,
    delete_user,
    get_user_detail,
    update_user_status,
)


@pytest.fixture
def sample_user() -> User:
    """Create a sample user for testing."""
    return User(
        id=1,
        email="test@example.com",
        full_name="Test User",
        password_hash="hashedpassword",
        is_active=True,
    )


async def test_get_user_detail_returns_user(sample_user: User) -> None:
    """get_user_detail returns user when found."""

    class MockRepo(UserRepository):
        async def get_by_id(self, user_id: int) -> User | None:
            return sample_user if user_id == 1 else None

    repo = MockRepo(session=None)  # type: ignore[arg-type]
    user = await get_user_detail(repo, 1)
    assert user.id == 1
    assert user.email == "test@example.com"


async def test_get_user_detail_raises_not_found() -> None:
    """get_user_detail raises error when user not found."""

    class MockRepo(UserRepository):
        async def get_by_id(self, _user_id: int) -> User | None:
            return None

    repo = MockRepo(session=None)  # type: ignore[arg-type]
    with pytest.raises(UserNotFoundError, match="User with ID 999 not found"):
        await get_user_detail(repo, 999)


async def test_update_user_status_changes_status(sample_user: User) -> None:
    """update_user_status changes user active status."""
    updated_user = User(
        id=1,
        email="test@example.com",
        full_name="Test User",
        password_hash="hashedpassword",
        is_active=False,
    )

    class MockRepo(UserRepository):
        async def get_by_id(self, user_id: int) -> User | None:
            return sample_user if user_id == 1 else None

        async def update(self, user: User) -> User:
            user.is_active = False
            return updated_user

    repo = MockRepo(session=None)  # type: ignore[arg-type]
    result = await update_user_status(1, False, repo)
    assert result.is_active is False


async def test_delete_user_removes_user(sample_user: User) -> None:
    """delete_user removes user from database."""
    deleted = False

    class MockRepo(UserRepository):
        async def get_by_id(self, user_id: int) -> User | None:
            return sample_user if user_id == 1 else None

        async def delete(self, _user_id: int) -> None:
            nonlocal deleted
            deleted = True

    repo = MockRepo(session=None)  # type: ignore[arg-type]
    await delete_user(1, repo, current_user_id=None)
    assert deleted


async def test_delete_user_prevents_self_deletion(sample_user: User) -> None:
    """delete_user prevents user from deleting themselves."""

    class MockRepo(UserRepository):
        async def get_by_id(self, user_id: int) -> User | None:
            return sample_user if user_id == 1 else None

    repo = MockRepo(session=None)  # type: ignore[arg-type]
    with pytest.raises(
        CannotDeleteCurrentUserError, match="Cannot delete the currently logged-in user"
    ):
        await delete_user(1, repo, current_user_id=1)


async def test_delete_user_allows_deleting_other_users(sample_user: User) -> None:
    """delete_user allows deleting other users."""
    deleted = False

    class MockRepo(UserRepository):
        async def get_by_id(self, user_id: int) -> User | None:
            return sample_user if user_id == 1 else None

        async def delete(self, _user_id: int) -> None:
            nonlocal deleted
            deleted = True

    repo = MockRepo(session=None)  # type: ignore[arg-type]
    await delete_user(1, repo, current_user_id=2)
    assert deleted
