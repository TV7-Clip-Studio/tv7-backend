from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Video
from app.services import videos as video_service


@pytest.mark.system
class TestVideoIngestSystem:
    async def test_ingest_creates_new_video(
        self,
        system_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await db_session.execute(delete(Video))
        await db_session.commit()

        enqueue_mock = AsyncMock()
        monkeypatch.setattr(video_service, "enqueue_video", enqueue_mock)

        response = await system_client.post(
            "/api/v1/videos/ingest",
            json={"youtube_url": "https://www.youtube.com/watch?v=abc123"},
        )
        assert response.status_code == 202
        payload = response.json()
        assert payload["created"] is True

        video_id = payload["video"]["id"]
        enqueue_mock.assert_awaited_once_with(
            video_id, source_url="https://www.youtube.com/watch?v=abc123", user_id=None
        )

        stored = (await db_session.execute(select(Video).where(Video.id == video_id))).scalar_one()
        assert stored.status == "ingested"

    async def test_ingest_duplicate_video_returns_existing(
        self,
        system_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await db_session.execute(delete(Video))
        await db_session.commit()

        video = Video(source_url="https://youtu.be/abc123", status="ready")
        db_session.add(video)
        await db_session.commit()

        enqueue_mock = AsyncMock()
        monkeypatch.setattr(video_service, "enqueue_video", enqueue_mock)

        response = await system_client.post(
            "/api/v1/videos/ingest",
            json={"youtube_url": "https://youtu.be/abc123"},
        )
        assert response.status_code == 202
        payload = response.json()
        assert payload["created"] is False
        assert payload["video"]["id"] == video.id

        enqueue_mock.assert_awaited_once_with(
            video.id, source_url="https://youtu.be/abc123", user_id=None
        )

    async def test_ingest_rejects_non_youtube(
        self,
        system_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        await db_session.execute(delete(Video))
        await db_session.commit()

        response = await system_client.post(
            "/api/v1/videos/ingest",
            json={"youtube_url": "https://example.com/video"},
        )
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["message"] == "URL must point to YouTube"
