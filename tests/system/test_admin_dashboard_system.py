from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.routes import SESSION_COOKIE_NAME
from app.db.models import Clip, ClipStatus, Video, VideoStatus


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


@pytest.mark.anyio
async def test_video_detail_redirects_without_session(app_client: AsyncClient) -> None:
    response = await app_client.get("/admin/videos/123", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


@pytest.mark.anyio
async def test_video_detail_returns_404_for_missing_video(
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

    response = await app_client.get("/admin/videos/99999")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_video_detail_renders_video_without_clips(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    video = Video(
        source_url="https://www.youtube.com/watch?v=test123",
        status=VideoStatus.INGESTED.value,
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.get(f"/admin/videos/{video.id}")
    assert response.status_code == 200
    assert f"Video #{video.id}" in response.text
    assert video.source_url in response.text
    assert "No clips generated yet" in response.text
    assert "Video is queued for processing" in response.text


@pytest.mark.anyio
async def test_video_detail_renders_video_with_clips(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    video = Video(
        source_url="https://www.youtube.com/watch?v=test456",
        status=VideoStatus.READY.value,
        transcript_text="This is a test transcript for the video.",
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    clip1 = Clip(
        video_id=video.id,
        start_sec=10,
        end_sec=25,
        caption_text="First clip hook",
        status=ClipStatus.READY.value,
        local_path="/media/clips/clip1.mp4",
    )
    clip2 = Clip(
        video_id=video.id,
        start_sec=45,
        end_sec=60,
        caption_text="Second clip hook",
        status=ClipStatus.RENDERING.value,
    )
    db_session.add_all([clip1, clip2])
    await db_session.commit()

    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.get(f"/admin/videos/{video.id}")
    assert response.status_code == 200
    assert f"Video #{video.id}" in response.text
    assert "Clips (2)" in response.text
    assert "1 ready" in response.text
    assert "1 rendering" in response.text
    assert "First clip hook" in response.text
    assert "Second clip hook" in response.text
    assert f"Clip #{clip1.id}" in response.text
    assert f"Clip #{clip2.id}" in response.text
    assert "10s → 25s" in response.text
    assert "45s → 60s" in response.text
    assert clip1.local_path in response.text
    assert "View transcript" in response.text


@pytest.mark.anyio
async def test_video_list_shows_clip_summary(
    app_client: AsyncClient,
    system_login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    video = Video(
        source_url="https://www.youtube.com/watch?v=summary_test",
        status=VideoStatus.PROCESSING.value,
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    clips = [
        Clip(video_id=video.id, start_sec=0, end_sec=10, status=ClipStatus.READY.value),
        Clip(video_id=video.id, start_sec=10, end_sec=20, status=ClipStatus.READY.value),
        Clip(video_id=video.id, start_sec=20, end_sec=30, status=ClipStatus.RENDERING.value),
    ]
    db_session.add_all(clips)
    await db_session.commit()

    email, password = system_login_credentials
    login_response = await app_client.post(
        "/admin/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    app_client.cookies.update(login_response.cookies)

    response = await app_client.get("/admin/videos")
    assert response.status_code == 200
    assert "3 clips" in response.text
    assert "2 ready" in response.text
    assert "1 rendering" in response.text
    assert "View details →" in response.text
    assert f"/admin/videos/{video.id}" in response.text
