from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import config as app_config
from app.db.models import Clip, ClipStatus, Video, VideoStatus
from app.services import tasks
from app.services.highlight_detector import ClipSegment
from app.services.youtube_downloader import DownloadResult


@pytest.mark.regression
async def test_full_pipeline_happy_path(
    session_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Run an end-to-end happy path of the pipeline with stubbed external services."""

    media_root = tmp_path / "media"
    monkeypatch.setattr(app_config.settings, "MEDIA_STORAGE_DIR", str(media_root))
    monkeypatch.setattr(app_config.settings, "OPENAI_API_KEY", "test-key", raising=False)

    def fake_download(video_id: int, _source_url: str) -> DownloadResult:
        storage_dir = media_root / "videos" / str(video_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        file_path = storage_dir / "source.mp4"
        file_path.write_bytes(b"fake video content")
        return DownloadResult(
            local_path=str(file_path),
            file_size_bytes=file_path.stat().st_size,
            transcript_text="segment one\nsegment two",
            transcript_language="en",
            duration_seconds=120,
        )

    async def fake_detect_highlights(
        *,
        transcript: str,
        duration_seconds: int,
        video_id: int,
        transcript_language: str | None = None,
    ) -> list[ClipSegment]:
        assert transcript.strip()
        assert duration_seconds == 120
        assert isinstance(video_id, int)
        assert transcript_language == "en"
        return [
            ClipSegment(start_sec=0, end_sec=30, hook="Hook 1"),
            ClipSegment(start_sec=35, end_sec=65, hook="Hook 2"),
            ClipSegment(start_sec=70, end_sec=100, hook="Hook 3"),
        ]

    monkeypatch.setattr(tasks, "download_video_and_transcript", fake_download, raising=False)
    monkeypatch.setattr(tasks, "detect_highlights_service", fake_detect_highlights, raising=False)

    async with session_factory() as session:
        video = Video(
            source_url="https://www.youtube.com/watch?v=stub", status=VideoStatus.INGESTED.value
        )
        session.add(video)
        await session.commit()
        await session.refresh(video)
        video_id = video.id

    await tasks._set_video_status(video_id, VideoStatus.PROCESSING)
    await tasks._download_video_task(video_id)

    async with session_factory() as session:
        refreshed = await session.get(Video, video_id)
        assert refreshed is not None
        assert refreshed.status == VideoStatus.PROCESSING.value
        assert refreshed.local_path and Path(refreshed.local_path).exists()
        assert refreshed.duration_seconds == 120
        assert refreshed.error_message is None

    await tasks._detect_highlights_task(video_id)

    async with session_factory() as session:
        clips = (
            (await session.execute(select(Clip).where(Clip.video_id == video_id))).scalars().all()
        )
        assert len(clips) == 3
        assert {clip.status for clip in clips} == {ClipStatus.RENDERING.value}

    await tasks._set_video_status(video_id, VideoStatus.READY)

    async with session_factory() as session:
        final_video = await session.get(Video, video_id)
        assert final_video is not None
        assert final_video.status == VideoStatus.READY.value
        assert final_video.error_message is None
