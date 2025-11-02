from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Video, VideoStatus
from app.services import tasks

pytestmark = pytest.mark.asyncio


async def test_process_video_sets_processing(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    video = Video(source_url="https://example.com", status=VideoStatus.INGESTED.value)
    db_session.add(video)
    await db_session.flush()
    await db_session.refresh(video)

    observed: list[int] = []
    monkeypatch.setattr(tasks.download_video, "send", lambda video_id: observed.append(video_id))

    await asyncio.to_thread(tasks.process_video, video.id)

    await db_session.refresh(video)
    assert video.status == VideoStatus.PROCESSING.value
    assert observed == [video.id]


async def test_finalize_video_marks_ready(db_session: AsyncSession) -> None:
    video = Video(source_url="https://example.com", status=VideoStatus.PROCESSING.value)
    db_session.add(video)
    await db_session.flush()
    await db_session.refresh(video)

    await asyncio.to_thread(tasks.finalize_video, video.id)

    await db_session.refresh(video)
    assert video.status == VideoStatus.READY.value
