from __future__ import annotations

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Clip, ClipStatus, PublishJob, PublishJobStatus, User, Video
from app.repositories.publish_jobs import PublishJobRepository

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def admin_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "secret")


async def _login_cookie(async_client: AsyncClient) -> dict[str, str]:
    response = await async_client.post(
        "/admin/login",
        data={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == HTTPStatus.SEE_OTHER
    session_cookie = response.cookies.get("admin_session")
    assert session_cookie
    async_client.cookies.set("admin_session", session_cookie, domain="testserver", path="/")
    return {"admin_session": session_cookie}


async def test_admin_login_and_dashboard(async_client: AsyncClient) -> None:
    await _login_cookie(async_client)

    response = await async_client.get("/admin/dashboard")
    assert response.status_code == HTTPStatus.OK
    assert "Dashboard" in response.text


async def test_admin_updates_publish_job(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    video = Video(source_url="local://job-test", ingest_type="upload", status="ready")
    clip = Clip(
        video=video,
        start_sec=0,
        end_sec=10,
        status=ClipStatus.READY.value,
    )
    db_session.add_all([video, clip])
    await db_session.flush()
    await db_session.refresh(clip)

    repo = PublishJobRepository(db_session)
    job = await repo.add_job(
        clip_id=clip.id,
        platform="tiktok",
        status=PublishJobStatus.PENDING,
    )
    await repo.commit()

    await _login_cookie(async_client)
    response = await async_client.post(
        f"/admin/schedule/{job.id}",
        data={
            "status_value": PublishJobStatus.COMPLETE.value,
            "asset_url": "https://cdn.example.com/clip.mp4",
            "response_payload": "ok",
        },
        follow_redirects=False,
    )
    assert response.status_code == HTTPStatus.SEE_OTHER

    updated: PublishJob | None = await db_session.get(PublishJob, job.id)
    assert updated is not None
    await db_session.refresh(updated)
    assert updated.status == PublishJobStatus.COMPLETE.value
    assert updated.asset_url == "https://cdn.example.com/clip.mp4"
    assert updated.response_payload == "ok"


async def test_admin_users_views(async_client: AsyncClient, db_session: AsyncSession) -> None:
    user = User(email="admin-test@example.com", full_name="Admin Test", password_hash="secret")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    video = Video(
        source_url="local://user-video",
        ingest_type="upload",
        status="ready",
        requested_by_user_id=user.id,
    )
    clip = Clip(video=video, start_sec=0, end_sec=5, status=ClipStatus.READY.value)
    db_session.add_all([video, clip])
    await db_session.flush()
    await db_session.refresh(clip)
    repo = PublishJobRepository(db_session)
    await repo.add_job(
        clip_id=clip.id,
        platform="youtube_shorts",
        status=PublishJobStatus.PENDING,
    )
    await repo.commit()

    await _login_cookie(async_client)

    list_response = await async_client.get("/admin/users")
    assert list_response.status_code == HTTPStatus.OK
    assert user.email in list_response.text

    detail_response = await async_client.get(f"/admin/users/{user.id}")
    assert detail_response.status_code == HTTPStatus.OK
    assert str(user.id) in detail_response.text
    assert "Videos" in detail_response.text
