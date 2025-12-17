from __future__ import annotations

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clip, Video
from app.repositories.videos import VideoRepository

pytestmark = pytest.mark.asyncio


async def test_register_local_video_with_clips(
    async_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "source_url": "local://video-123",
        "title": "Test Video",
        "duration_seconds": 120,
        "file_size_bytes": 1024,
        "clip_generation_mode": "replace",
        "clips": [
            {
                "start_sec": 0,
                "end_sec": 30,
                "asset_url": "/media/uploads/assets/clip1.mp4",
                "caption_text": "Hook 1",
            }
        ],
    }

    response = await async_client.post(
        "/api/v1/videos/local",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["source_url"] == payload["source_url"]
    assert body["ingest_type"] == "upload"
    assert body["status"] == "ready"
    assert len(body["clips"]) == 1

    video_id = body["id"]
    fetched = await async_client.get(f"/api/v1/videos/{video_id}", headers=auth_headers)
    assert fetched.status_code == HTTPStatus.OK
    fetched_body = fetched.json()
    assert fetched_body["original_filename"] == payload["title"]
    assert fetched_body["clips"][0]["caption_text"] == "Hook 1"


async def test_create_additional_clip(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    repo = VideoRepository(db_session)
    video = Video(source_url="local://existing", status="ready", ingest_type="upload")
    await repo.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    clip_payload = {"start_sec": 10, "end_sec": 20, "asset_url": "/media/clip2.mp4"}
    response = await async_client.post(
        f"/api/v1/videos/{video.id}/clips",
        json=clip_payload,
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    created = response.json()
    assert created["video_id"] == video.id
    assert created["asset_url"] == clip_payload["asset_url"]

    refreshed = await repo.get_with_clips(video.id)
    assert refreshed is not None
    assert any(
        isinstance(c, Clip) and c.asset_url == clip_payload["asset_url"] for c in refreshed.clips
    )


async def test_list_videos_returns_clips(
    async_client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    repo = VideoRepository(db_session)
    video = Video(source_url="local://listed", status="ready", ingest_type="upload")
    video.clips.append(Clip(start_sec=0, end_sec=15, asset_url="/media/clip3.mp4"))
    await repo.add(video)
    await db_session.commit()

    response = await async_client.get("/api/v1/videos", headers=auth_headers)
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert isinstance(body, list)
    assert any(v["source_url"] == "local://listed" and v["clips"] for v in body)
