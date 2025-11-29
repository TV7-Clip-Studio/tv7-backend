from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clip, Video


@pytest.mark.system
async def test_register_local_video_creates_video_and_clips(
    system_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await db_session.execute(delete(Clip))
    await db_session.execute(delete(Video))
    await db_session.commit()

    payload = {
        "source_url": "local://video-123",
        "local_path": "/tmp/video.mp4",
        "original_filename": "video.mp4",
        "upload_checksum": "abc123",
        "upload_file_size_bytes": 12345,
        "duration_seconds": 42,
        "file_size_bytes": 12345,
        "transcript_text": "hello world",
        "transcript_language": "en",
        "workspace_root": "/tmp/workspace/video-123",
        "status": "ready",
        "clips": [
            {
                "start_sec": 0,
                "end_sec": 10,
                "local_path": "/tmp/clip1.mp4",
                "caption_text": "hello",
                "ready_local_only": True,
                "asset_url": None,
                "asset_checksum": None,
                "asset_size_bytes": None,
                "render_width": 1080,
                "render_height": 1920,
                "frame_rate": 30.0,
                "file_size_bytes": 2048,
                "status": "ready",
            }
        ],
    }

    resp = await system_client.post("/api/v1/videos/local", json=payload)
    assert resp.status_code == 201, resp.text
    video_data = resp.json()
    assert video_data["source_url"] == payload["source_url"]
    assert video_data["ingest_type"] == "upload"
    assert video_data["status"] == "ready"
    assert len(video_data["clips"]) == 1
    clip_data = video_data["clips"][0]
    assert clip_data["ready_local_only"] is True
    assert clip_data["caption_text"] == "hello"

    stored_video = (
        await db_session.execute(select(Video).where(Video.source_url == payload["source_url"]))
    ).scalar_one()
    assert stored_video.local_path is None
    stored_clip = (
        await db_session.execute(select(Clip).where(Clip.video_id == stored_video.id))
    ).scalar_one()
    assert stored_clip.ready_local_only is True
    assert stored_clip.caption_text == "hello"
