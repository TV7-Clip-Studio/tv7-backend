from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Video
from app.deps import db as db_deps
from app.main import app

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def override_db_dependency(db_session: AsyncSession) -> Generator[None, None, None]:
    async def _override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[db_deps.get_session] = _override
    yield
    app.dependency_overrides.pop(db_deps.get_session, None)


async def test_ingest_creates_video(
    async_client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    with patch("app.services.videos.enqueue_video", new=AsyncMock()) as mock_enqueue:
        response = await async_client.post(
            "/api/v1/videos/ingest",
            json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=auth_headers,
        )
    assert response.status_code == 202
    data = response.json()
    assert data["created"] is True
    assert data["queued"] is True
    assert "video" in data
    video_id = data["video"]["id"]

    mock_enqueue.assert_awaited_once_with(
        video_id, source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", user_id=None
    )

    stored = (await db_session.execute(select(Video).where(Video.id == video_id))).scalar_one()
    assert stored.source_url.endswith("dQw4w9WgXcQ")
    assert stored.status == "ingested"


async def test_ingest_requeues_existing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    video = Video(source_url="https://youtu.be/abc123", status="processing")
    db_session.add(video)
    await db_session.flush()

    with patch("app.services.videos.enqueue_video", new=AsyncMock()) as mock_enqueue:
        response = await async_client.post(
            "/api/v1/videos/ingest",
            json={"youtube_url": "https://youtu.be/abc123"},
            headers=auth_headers,
        )

    assert response.status_code == 202
    data = response.json()
    assert data["created"] is False
    assert data["video"]["id"] == video.id

    mock_enqueue.assert_awaited_once_with(
        video.id, source_url="https://youtu.be/abc123", user_id=None
    )


async def test_ingest_rejects_non_youtube(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await async_client.post(
        "/api/v1/videos/ingest",
        json={"youtube_url": "https://example.com/video"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_ingest_append_flag_sets_mode(
    async_client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    with patch("app.services.videos.enqueue_video", new=AsyncMock()):
        response = await async_client.post(
            "/api/v1/videos/ingest",
            json={
                "youtube_url": "https://www.youtube.com/watch?v=append123",
                "append_clips": True,
            },
            headers=auth_headers,
        )
    assert response.status_code == 202
    video_id = response.json()["video"]["id"]
    stored = (await db_session.execute(select(Video).where(Video.id == video_id))).scalar_one()
    assert stored.clip_generation_mode == "append"
