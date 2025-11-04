from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.admin.routes import SESSION_COOKIE_NAME


@pytest.mark.anyio
async def test_admin_login_page_renders(app_client: AsyncClient) -> None:
    response = await app_client.get("/admin/login")
    assert response.status_code == 200
    assert "Operator Sign In" in response.text


@pytest.mark.anyio
async def test_admin_login_rejects_invalid_credentials(app_client: AsyncClient) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": "nobody@example.com", "password": "bad-password"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.text


@pytest.mark.anyio
async def test_admin_login_sets_cookie_and_allows_dashboard(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/admin/videos"
    session_cookie = login_response.cookies.get(SESSION_COOKIE_NAME)
    assert session_cookie

    app_client.cookies.update(login_response.cookies)
    dashboard = await app_client.get("/admin/videos")
    assert dashboard.status_code == 200
    assert "Recent videos" in dashboard.text


@pytest.mark.anyio
async def test_dashboard_redirects_without_session(app_client: AsyncClient) -> None:
    response = await app_client.get("/admin/videos", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


@pytest.mark.anyio
async def test_ingest_form_handles_invalid_url(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.post(
        "/admin/videos/ingest",
        data={"youtube_url": "https://example.com/not-youtube"},
    )
    assert response.status_code == 422
    assert "URL must point to YouTube" in response.text


@pytest.mark.anyio
async def test_ingest_form_queues_video(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
) -> None:
    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.post(
        "/admin/videos/ingest",
        data={"youtube_url": "https://www.youtube.com/watch?v=demo"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/videos?flash=")

    app_client.cookies.update(response.cookies)
    follow_up = await app_client.get(response.headers["location"])
    assert follow_up.status_code == 200
    assert "Video queued for processing" in follow_up.text
