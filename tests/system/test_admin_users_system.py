"""System tests for admin user management pages."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.admin.routes import SESSION_COOKIE_NAME


@pytest.mark.system
async def test_users_list_requires_auth(app_client: AsyncClient) -> None:
    """Users list page requires authentication."""
    resp = await app_client.get("/admin/users", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


@pytest.mark.system
async def test_users_list_shows_users(
    app_client: AsyncClient, system_login_credentials: tuple[str, str]
) -> None:
    """Users list page displays all users."""
    email, password = system_login_credentials
    login_resp = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303
    app_client.cookies.update(login_resp.cookies)

    resp = await app_client.get("/admin/users")
    assert resp.status_code == 200
    html = resp.text
    assert "User Management" in html
    assert "Users" in html
    # The authenticated user should be listed
    assert email in html


@pytest.mark.system
async def test_user_detail_requires_auth(app_client: AsyncClient) -> None:
    """User detail page requires authentication."""
    resp = await app_client.get("/admin/users/1", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


@pytest.mark.system
async def test_user_detail_shows_user_info(
    app_client: AsyncClient, system_login_credentials: tuple[str, str]
) -> None:
    """User detail page displays user information."""
    email, password = system_login_credentials
    login_resp = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_resp.cookies)

    # Try to access user detail page - user ID 1 should exist
    resp = await app_client.get("/admin/users/1")
    assert resp.status_code == 200
    html = resp.text
    assert "User Information" in html
    assert "Account Metadata" in html


@pytest.mark.system
async def test_user_detail_nonexistent_user_404(
    app_client: AsyncClient, system_login_credentials: tuple[str, str]
) -> None:
    """User detail page returns 404 for nonexistent user."""
    email, password = system_login_credentials
    login_resp = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_resp.cookies)

    resp = await app_client.get("/admin/users/99999")
    assert resp.status_code == 404


@pytest.mark.system
async def test_toggle_user_status_requires_auth(app_client: AsyncClient) -> None:
    """Toggle user status requires authentication."""
    resp = await app_client.post("/admin/users/1/toggle-status", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


@pytest.mark.system
async def test_toggle_user_status_redirects_to_detail(
    app_client: AsyncClient, system_login_credentials: tuple[str, str]
) -> None:
    """Toggle user status redirects back to detail page."""
    email, password = system_login_credentials
    login_resp = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_resp.cookies)

    # Toggle status for user 1
    resp = await app_client.post("/admin/users/1/toggle-status", follow_redirects=False)
    assert resp.status_code == 303
    assert "/admin/users/1" in resp.headers["location"]
    assert "flash=" in resp.headers["location"]


@pytest.mark.system
async def test_delete_user_requires_auth(app_client: AsyncClient) -> None:
    """Delete user requires authentication."""
    resp = await app_client.post("/admin/users/1/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


@pytest.mark.system
async def test_cannot_delete_current_user(
    app_client: AsyncClient, system_login_credentials: tuple[str, str]
) -> None:
    """Current user cannot delete themselves."""
    email, password = system_login_credentials
    login_resp = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_resp.cookies)

    # Try to delete user 1 (assuming current user)
    delete_resp = await app_client.post("/admin/users/1/delete", follow_redirects=False)
    assert delete_resp.status_code == 303
    # Should redirect back with error
    assert "error=" in delete_resp.headers["location"]
