from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.db.models import Video
from app.deps import db as db_deps
from app.main import app
from app.services.upload_storage import StoredUpload, UploadTooLargeError

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def override_db_dependency(db_session: AsyncSession) -> Generator[None, None, None]:
    async def _override() -> AsyncGenerator[AsyncSession, None]:
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
            "/api/v1/videos/ingest/youtube",
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
            "/api/v1/videos/ingest/youtube",
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
        "/api/v1/videos/ingest/youtube",
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
            "/api/v1/videos/ingest/youtube",
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


async def test_upload_ingest_creates_video(
    async_client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    temp_source = tmp_path / "source.mp4"
    temp_source.write_bytes(b"binary-video")

    async def fake_persist(upload: UploadFile) -> StoredUpload:
        await upload.read()
        return StoredUpload(
            temp_path=temp_source,
            original_filename="demo.mp4",
            file_size_bytes=temp_source.stat().st_size,
            checksum="abc123",
        )

    with (
        patch("app.api.v1.videos.persist_upload_temporarily", new=fake_persist),
        patch("app.services.videos.enqueue_video", new=AsyncMock()) as mock_enqueue,
    ):
        response = await async_client.post(
            "/api/v1/videos/ingest/upload",
            headers=auth_headers,
            files={"file": ("demo.mp4", b"file-bytes", "video/mp4")},
        )

    assert response.status_code == 202
    payload = response.json()
    video_id = payload["video"]["id"]
    stored = (await db_session.execute(select(Video).where(Video.id == video_id))).scalar_one()
    assert stored.ingest_type == "upload"
    assert stored.original_filename == "demo.mp4"
    mock_enqueue.assert_awaited_once()


async def test_upload_ingest_handles_large_file_error(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    async def fake_persist(_: UploadFile) -> StoredUpload:
        raise UploadTooLargeError("too big")

    with patch("app.api.v1.videos.persist_upload_temporarily", new=fake_persist):
        response = await async_client.post(
            "/api/v1/videos/ingest/upload",
            headers=auth_headers,
            files={"file": ("demo.mp4", b"file-bytes", "video/mp4")},
        )

    assert response.status_code == 413
