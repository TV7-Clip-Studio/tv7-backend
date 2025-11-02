from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clip, ClipStatus, Video, VideoStatus


@pytest.mark.asyncio
async def test_video_defaults(db_session: AsyncSession) -> None:
    video = Video(source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    db_session.add(video)
    await db_session.flush()
    await db_session.refresh(video)

    assert video.status == VideoStatus.INGESTED.value
    assert video.created_at is not None
    assert video.updated_at is not None


@pytest.mark.asyncio
async def test_clip_relationship(db_session: AsyncSession) -> None:
    video = Video(source_url="https://example.com/video")
    clip = Clip(start_sec=10, end_sec=25)
    video.clips.append(clip)
    db_session.add(video)
    await db_session.flush()

    assert clip.status == ClipStatus.RENDERING.value
    assert clip.video_id == video.id

    fetched = (await db_session.execute(select(Video).where(Video.id == video.id))).scalar_one()
    assert len(fetched.clips) == 1


@pytest.mark.asyncio
async def test_cascade_delete(db_session: AsyncSession) -> None:
    video = Video(source_url="https://example.com/delete")
    video.clips.append(Clip(start_sec=0, end_sec=15))
    db_session.add(video)
    await db_session.flush()

    await db_session.delete(video)
    await db_session.flush()

    clip_rows = (await db_session.execute(select(Clip))).scalars().all()
    assert clip_rows == []
