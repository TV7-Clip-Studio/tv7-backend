from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.schemas import UserUpdate
from app.services.users import update_user_profile


@pytest.mark.anyio
async def test_get_current_user_returns_profile(
    authenticated_client: AsyncClient,
    test_user: User,
) -> None:
    """GET /api/v1/users/me returns the authenticated user's profile."""
    response = await authenticated_client.get("/api/v1/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_user.id
    assert data["email"] == test_user.email
    assert data["full_name"] == test_user.full_name


@pytest.mark.anyio
async def test_get_current_user_requires_authentication(app_client: AsyncClient) -> None:
    """GET /api/v1/users/me returns 401 without auth."""
    response = await app_client.get("/api/v1/users/me")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_update_current_user_full_name(
    authenticated_client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """PATCH /api/v1/users/me updates full name."""
    response = await authenticated_client.patch(
        "/api/v1/users/me",
        json={"full_name": "Updated Name"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Updated Name"
    assert data["email"] == test_user.email

    # Verify in database
    await db_session.refresh(test_user)
    assert test_user.full_name == "Updated Name"


@pytest.mark.anyio
async def test_update_current_user_email(
    authenticated_client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """PATCH /api/v1/users/me updates email."""
    new_email = "newemail@example.com"
    response = await authenticated_client.patch(
        "/api/v1/users/me",
        json={"email": new_email},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == new_email

    # Verify in database
    await db_session.refresh(test_user)
    assert test_user.email == new_email


@pytest.mark.anyio
async def test_update_current_user_email_conflict(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    password_hash: str,
) -> None:
    """PATCH /api/v1/users/me returns 409 if email is taken."""
    # Create another user
    other_user = User(
        email="other@example.com",
        full_name="Other User",
        password_hash=password_hash,
    )
    db_session.add(other_user)
    await db_session.commit()

    # Try to update to other user's email
    response = await authenticated_client.patch(
        "/api/v1/users/me",
        json={"email": "other@example.com"},
    )
    assert response.status_code == 409
    assert "already in use" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_update_current_user_password(
    authenticated_client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """PATCH /api/v1/users/me changes password with correct current password."""
    response = await authenticated_client.patch(
        "/api/v1/users/me",
        json={
            "current_password": "password123",
            "new_password": "newpassword456",
        },
    )
    assert response.status_code == 200

    # Verify password was actually changed by trying to authenticate
    from app.core.security import verify_password

    await db_session.refresh(test_user)
    assert verify_password("newpassword456", test_user.password_hash)
    assert not verify_password("password123", test_user.password_hash)


@pytest.mark.anyio
async def test_update_current_user_password_wrong_current(
    authenticated_client: AsyncClient,
) -> None:
    """PATCH /api/v1/users/me returns 400 with incorrect current password."""
    response = await authenticated_client.patch(
        "/api/v1/users/me",
        json={
            "current_password": "wrongpassword",
            "new_password": "newpassword456",
        },
    )
    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_update_current_user_password_without_current(
    authenticated_client: AsyncClient,
) -> None:
    """PATCH /api/v1/users/me returns 400 when changing password without current."""
    response = await authenticated_client.patch(
        "/api/v1/users/me",
        json={"new_password": "newpassword456"},
    )
    assert response.status_code == 400
    assert "required" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_update_current_user_requires_authentication(
    app_client: AsyncClient,
) -> None:
    """PATCH /api/v1/users/me returns 401 without auth."""
    response = await app_client.patch(
        "/api/v1/users/me",
        json={"full_name": "New Name"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_update_current_user_multiple_fields(
    authenticated_client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """PATCH /api/v1/users/me updates multiple fields at once."""
    response = await authenticated_client.patch(
        "/api/v1/users/me",
        json={
            "full_name": "New Name",
            "email": "newemail@example.com",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "New Name"
    assert data["email"] == "newemail@example.com"

    # Verify in database
    await db_session.refresh(test_user)
    assert test_user.full_name == "New Name"
    assert test_user.email == "newemail@example.com"
