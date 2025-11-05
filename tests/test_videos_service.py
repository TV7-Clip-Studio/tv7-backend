from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clip, ClipStatus, Video, VideoStatus
from app.repositories.videos import VideoRepository
from app.services.videos import list_videos


@pytest.mark.anyio("asyncio")
async def test_list_videos_returns_summary(db_session: AsyncSession) -> None:
    video = Video(
        source_url="https://youtube.com/watch?v=test", status=VideoStatus.PROCESSING.value
    )
    db_session.add(video)
    await db_session.flush()

    now = datetime.now(tz=UTC)
    clips = [
        Clip(
            video_id=video.id,
            start_sec=0,
            end_sec=30,
            status=ClipStatus.RENDERING.value,
            updated_at=now - timedelta(minutes=5),
        ),
        Clip(
            video_id=video.id,
            start_sec=30,
            end_sec=60,
            status=ClipStatus.READY.value,
            updated_at=now,
        ),
        Clip(
            video_id=video.id,
            start_sec=60,
            end_sec=90,
            status=ClipStatus.PUBLISHED_PARTIAL.value,
            updated_at=now - timedelta(minutes=1),
        ),
    ]
    db_session.add_all(clips)
    await db_session.commit()

    repo = VideoRepository(db_session)
    entries = await list_videos(repo)

    entry = next(e for e in entries if e.video.id == video.id)
    assert entry.video.id == video.id
    summary = entry.clips
    assert summary.total == 3
    assert summary.ready == 1
    assert summary.rendering == 1
    assert summary.published == 1
    assert summary.errored == 0
    assert summary.latest_updated_at == clips[1].updated_at


@pytest.mark.anyio("asyncio")
async def test_list_videos_handles_videos_without_clips(db_session: AsyncSession) -> None:
    video = Video(source_url="https://youtube.com/watch?v=empty", status=VideoStatus.INGESTED.value)
    db_session.add(video)
    await db_session.commit()

    repo = VideoRepository(db_session)
    entries = await list_videos(repo)

    entry = next(e for e in entries if e.video.id == video.id)
    summary = entry.clips
    assert summary.total == 0
    assert all(count == 0 for count in summary.counts.values())
    assert summary.latest_updated_at is None
