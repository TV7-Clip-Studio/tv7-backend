from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


@pytest.mark.anyio
async def test_profile_page_redirects_without_session(app_client: AsyncClient) -> None:
    """GET /admin/profile redirects to login without authentication."""
    response = await app_client.get("/admin/profile", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


@pytest.mark.anyio
async def test_profile_page_renders_with_user_data(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    """GET /admin/profile displays user information."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.get("/admin/profile")
    assert response.status_code == 200
    assert "Your Profile" in response.text
    assert "Account Information" in response.text
    assert email in response.text
    assert "Update Profile" in response.text
    assert "Change Password" in response.text


@pytest.mark.anyio
async def test_profile_update_full_name(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    """POST /admin/profile updates full name."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.post(
        "/admin/profile",
        data={
            "action": "update_profile",
            "full_name": "Updated Name",
            "email": email,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "flash=Profile updated successfully" in response.headers["location"]

    # Verify profile page shows updated name
    follow_up = await app_client.get("/admin/profile")
    assert "Updated Name" in follow_up.text


@pytest.mark.anyio
async def test_profile_update_email(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    """POST /admin/profile updates email."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    new_email = "newemail@example.com"
    response = await app_client.post(
        "/admin/profile",
        data={
            "action": "update_profile",
            "full_name": "Test User",
            "email": new_email,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    # Verify profile page shows updated email
    follow_up = await app_client.get("/admin/profile")
    assert new_email in follow_up.text


@pytest.mark.anyio
async def test_profile_update_email_conflict(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
    db_session: AsyncSession,
    password_hash: str,
) -> None:
    """POST /admin/profile shows error when email is taken."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    # Create another user
    other_user = User(
        email="other@example.com",
        full_name="Other User",
        password_hash=password_hash,
    )
    db_session.add(other_user)
    await db_session.commit()

    # Try to update to other user's email
    response = await app_client.post(
        "/admin/profile",
        data={
            "action": "update_profile",
            "full_name": "Test User",
            "email": "other@example.com",
        },
    )
    assert response.status_code == 400
    assert "already in use" in response.text.lower()


@pytest.mark.anyio
async def test_profile_change_password_success(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    """POST /admin/profile changes password with correct current password."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.post(
        "/admin/profile",
        data={
            "action": "change_password",
            "current_password": password,
            "new_password": "newpassword456",
            "confirm_password": "newpassword456",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "flash=Password changed successfully" in response.headers["location"]


@pytest.mark.anyio
async def test_profile_change_password_wrong_current(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    """POST /admin/profile shows error with wrong current password."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.post(
        "/admin/profile",
        data={
            "action": "change_password",
            "current_password": "wrongpassword",
            "new_password": "newpassword456",
            "confirm_password": "newpassword456",
        },
    )
    assert response.status_code == 400
    assert "incorrect" in response.text.lower()


@pytest.mark.anyio
async def test_profile_change_password_mismatch(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    """POST /admin/profile shows error when passwords don't match."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.post(
        "/admin/profile",
        data={
            "action": "change_password",
            "current_password": password,
            "new_password": "newpassword456",
            "confirm_password": "differentpassword",
        },
    )
    assert response.status_code == 400
    assert "do not match" in response.text.lower()


@pytest.mark.anyio
async def test_profile_change_password_missing_fields(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    """POST /admin/profile shows error when password fields are missing."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.post(
        "/admin/profile",
        data={
            "action": "change_password",
            "new_password": "newpassword456",
            "confirm_password": "newpassword456",
        },
    )
    assert response.status_code == 400
    assert "required" in response.text.lower()


@pytest.mark.anyio
async def test_profile_displays_flash_message(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    """GET /admin/profile?flash=... displays flash message."""
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.get("/admin/profile?flash=Test+message")
    assert response.status_code == 200
    assert "Test message" in response.text
