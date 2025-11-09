from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clip, ClipGenerationMode, ClipStatus, Video, VideoStatus
from app.services import tasks
from app.services.highlight_detector import ClipSegment, HighlightDetectionError
from app.services.youtube_downloader import DownloadError, DownloadResult

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


async def test_run_pipeline_inline_happy_path(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = Video(source_url="https://youtube.com/watch?v=stub", status=VideoStatus.INGESTED.value)
    db_session.add(video)
    await db_session.flush()
    await db_session.refresh(video)

    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    file_path = media_root / "source.mp4"

    def fake_download(
        _video_id: int, _source_url: str, *, access_token: str | None = None
    ) -> DownloadResult:
        del access_token
        file_path.write_bytes(b"video-bytes")
        return DownloadResult(
            local_path=str(file_path),
            file_size_bytes=file_path.stat().st_size,
            transcript_text="hello world",
            transcript_language="en",
            duration_seconds=120,
        )

    async def fake_detect(
        *,
        transcript: str,
        duration_seconds: int,
        video_id: int,
        transcript_language: str | None = None,
    ) -> list[ClipSegment]:
        assert transcript == "hello world"
        assert duration_seconds == 120
        assert video_id == video.id
        assert transcript_language == "en"
        return [
            ClipSegment(start_sec=0, end_sec=30, hook="Hook 1"),
            ClipSegment(start_sec=40, end_sec=70, hook="Hook 2"),
        ]

    monkeypatch.setattr(tasks, "download_video_and_transcript", fake_download, raising=False)
    monkeypatch.setattr(tasks, "detect_highlights_service", fake_detect, raising=False)

    await tasks.run_pipeline_inline(video.id)

    await db_session.refresh(video)
    assert video.status == VideoStatus.READY.value
    assert video.local_path == str(file_path)
    assert video.duration_seconds == 120
    assert video.file_size_bytes == file_path.stat().st_size
    assert video.error_message is None
    assert video.transcript_language == "en"

    clips = (
        (await db_session.execute(select(Clip).where(Clip.video_id == video.id))).scalars().all()
    )
    assert len(clips) == 2
    assert all(clip.status == ClipStatus.RENDERING.value for clip in clips)


async def test_run_pipeline_inline_handles_errors(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = Video(source_url="https://youtube.com/watch?v=fail", status=VideoStatus.INGESTED.value)
    db_session.add(video)
    await db_session.flush()
    await db_session.refresh(video)

    def failing_download(
        _video_id: int, _source_url: str, *, access_token: str | None = None
    ) -> DownloadResult:
        del access_token
        raise DownloadError("boom")

    async def error_highlights(**_: object) -> list[ClipSegment]:
        raise HighlightDetectionError("should not run")

    monkeypatch.setattr(tasks, "download_video_and_transcript", failing_download, raising=False)
    monkeypatch.setattr(tasks, "detect_highlights_service", error_highlights, raising=False)

    await tasks.run_pipeline_inline(video.id)

    await db_session.refresh(video)
    assert video.status == VideoStatus.ERROR.value
    assert "boom" in (video.error_message or "")


async def test_detect_highlights_replaces_existing_clips(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = Video(
        source_url="https://youtube.com/watch?v=replace",
        status=VideoStatus.PROCESSING.value,
        transcript_text="hello world",
        transcript_language="en",
        duration_seconds=180,
        clip_generation_mode=ClipGenerationMode.REPLACE.value,
    )
    db_session.add(video)
    await db_session.flush()
    await db_session.refresh(video)

    async def fake_segments_one(**_: object) -> list[ClipSegment]:
        return [
            ClipSegment(start_sec=0, end_sec=30, hook="First"),
            ClipSegment(start_sec=30, end_sec=60, hook="Second"),
        ]

    async def fake_segments_two(**_: object) -> list[ClipSegment]:
        return [
            ClipSegment(start_sec=60, end_sec=120, hook="Third"),
        ]

    monkeypatch.setattr(tasks, "detect_highlights_service", fake_segments_one, raising=False)
    await tasks._detect_highlights_task(video.id)

    monkeypatch.setattr(tasks, "detect_highlights_service", fake_segments_two, raising=False)
    await tasks._detect_highlights_task(video.id)

    rows = (await db_session.execute(select(Clip).where(Clip.video_id == video.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].start_sec == 60
    assert video.clip_generation_mode == ClipGenerationMode.REPLACE.value


async def test_detect_highlights_append_mode_appends(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = Video(
        source_url="https://youtube.com/watch?v=append",
        status=VideoStatus.PROCESSING.value,
        transcript_text="hello world",
        transcript_language="en",
        duration_seconds=200,
        clip_generation_mode=ClipGenerationMode.REPLACE.value,
    )
    db_session.add(video)
    await db_session.flush()
    await db_session.refresh(video)

    async def first_segments(**_: object) -> list[ClipSegment]:
        return [ClipSegment(start_sec=0, end_sec=30, hook="First")]

    async def second_segments(**_: object) -> list[ClipSegment]:
        return [ClipSegment(start_sec=30, end_sec=60, hook="Second")]

    monkeypatch.setattr(tasks, "detect_highlights_service", first_segments, raising=False)
    await tasks._detect_highlights_task(video.id)

    video.clip_generation_mode = ClipGenerationMode.APPEND.value
    await db_session.flush()

    monkeypatch.setattr(tasks, "detect_highlights_service", second_segments, raising=False)
    await tasks._detect_highlights_task(video.id)

    rows = (
        (
            await db_session.execute(
                select(Clip).where(Clip.video_id == video.id).order_by(Clip.start_sec)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert [clip.start_sec for clip in rows] == [0, 30]
    await db_session.refresh(video)
    assert video.clip_generation_mode == ClipGenerationMode.REPLACE.value


async def test_download_task_skips_when_assets_cached(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage_dir = tmp_path / "videos" / "1"
    storage_dir.mkdir(parents=True)
    file_path = storage_dir / "source.mp4"
    file_path.write_bytes(b"cached")

    video = Video(
        source_url="https://youtube.com/watch?v=cached",
        status=VideoStatus.PROCESSING.value,
        local_path=str(file_path),
        transcript_text="already here",
        transcript_language="en",
        duration_seconds=180,
        clip_generation_mode=ClipGenerationMode.APPEND.value,
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    def fail_download(*_: object, **__: object) -> DownloadResult:  # pragma: no cover
        raise AssertionError("Downloader should not be called")

    monkeypatch.setattr(tasks, "download_video_and_transcript", fail_download, raising=False)

    await tasks._download_video_task(video.id)

    await db_session.refresh(video)
    assert video.local_path == str(file_path)
    assert video.transcript_text == "already here"
