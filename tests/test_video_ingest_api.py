from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import videos as videos_module
from app.db.models import Video
from app.main import app

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def override_db_dependency(db_session: AsyncSession) -> Generator[None, None, None]:
    async def _override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[videos_module.get_db_session] = _override
    yield
    app.dependency_overrides.pop(videos_module.get_db_session, None)


async def test_ingest_creates_video(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BETA_API_KEY", "dev-beta-key")
    with patch("app.api.v1.videos.enqueue_video", new=AsyncMock()) as mock_enqueue:
        response = await async_client.post(
            "/api/v1/videos/ingest",
            json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"X-API-Key": "dev-beta-key"},
        )
    assert response.status_code == 202
    data = response.json()
    assert data["created"] is True
    assert data["queued"] is True
    assert "video" in data
    video_id = data["video"]["id"]

    mock_enqueue.assert_awaited_once_with(
        video_id, source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )

    stored = (await db_session.execute(select(Video).where(Video.id == video_id))).scalar_one()
    assert stored.source_url.endswith("dQw4w9WgXcQ")
    assert stored.status == "ingested"


async def test_ingest_requeues_existing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BETA_API_KEY", "dev-beta-key")
    video = Video(source_url="https://youtu.be/abc123", status="processing")
    db_session.add(video)
    await db_session.flush()

    with patch("app.api.v1.videos.enqueue_video", new=AsyncMock()) as mock_enqueue:
        response = await async_client.post(
            "/api/v1/videos/ingest",
            json={"youtube_url": "https://youtu.be/abc123"},
            headers={"X-API-Key": "dev-beta-key"},
        )

    assert response.status_code == 202
    data = response.json()
    assert data["created"] is False
    assert data["video"]["id"] == video.id

    mock_enqueue.assert_awaited_once_with(video.id, source_url="https://youtu.be/abc123")


async def test_ingest_rejects_non_youtube(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BETA_API_KEY", "dev-beta-key")
    response = await async_client.post(
        "/api/v1/videos/ingest",
        json={"youtube_url": "https://example.com/video"},
        headers={"X-API-Key": "dev-beta-key"},
    )
    assert response.status_code == 422
