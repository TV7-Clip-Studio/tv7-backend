from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Clip,
    ClipGenerationMode,
    ClipStatus,
    Video,
    VideoIngestType,
    VideoStatus,
)
from app.services import render_workspace, tasks
from app.services.clipper import ClipRenderError, ClipRenderResult
from app.services.highlight_detector import ClipSegment, HighlightDetectionError
from app.services.render_workspace import VideoWorkspace
from app.services.transcription import TranscriptResult
from app.services.video_normalizer import VideoNormalizationResult
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
    monkeypatch.setattr(
        render_workspace.settings, "MEDIA_STORAGE_DIR", str(media_root), raising=False
    )
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

    def fake_render(
        video_obj: Video,
        clip_obj: Clip,
        workspace_obj: VideoWorkspace,
        *,
        overwrite: bool = False,
    ) -> ClipRenderResult:
        del video_obj, overwrite
        paths = workspace_obj.clip_paths(clip_obj.id)
        paths.final_path.parent.mkdir(parents=True, exist_ok=True)
        paths.final_path.write_bytes(b"clip-bytes")
        return ClipRenderResult(
            final_path=paths.final_path,
            public_url=paths.public_url,
            width=1080,
            height=1920,
            frame_rate=30.0,
            file_size_bytes=paths.final_path.stat().st_size,
        )

    monkeypatch.setattr(tasks, "download_video_and_transcript", fake_download, raising=False)
    monkeypatch.setattr(tasks, "detect_highlights_service", fake_detect, raising=False)
    monkeypatch.setattr(tasks, "render_clip", fake_render, raising=False)

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
    assert all(clip.status == ClipStatus.READY.value for clip in clips)
    assert all(clip.local_path for clip in clips)


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


async def test_download_video_task_handles_upload_ingest(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    upload_path = tmp_path / "incoming.mov"
    upload_path.write_bytes(b"raw")

    video = Video(
        source_url="upload://example",
        status=VideoStatus.INGESTED.value,
        ingest_type=VideoIngestType.UPLOAD.value,
        clip_generation_mode=ClipGenerationMode.REPLACE.value,
        upload_original_path=str(upload_path),
    )
    db_session.add(video)
    await db_session.flush()
    await db_session.refresh(video)

    def fake_normalize(video_id: int, source_path: Path) -> VideoNormalizationResult:
        destination_dir = tmp_path / "videos" / str(video_id)
        destination_dir.mkdir(parents=True, exist_ok=True)
        final = destination_dir / "source.mp4"
        final.write_bytes(b"normalized")
        Path(source_path).unlink(missing_ok=True)
        return VideoNormalizationResult(
            normalized_path=str(final),
            file_size_bytes=final.stat().st_size,
            duration_seconds=130,
        )

    async def fake_transcribe(_: str) -> TranscriptResult:
        return TranscriptResult(text="hola mundo", language_code="es")

    monkeypatch.setattr(tasks, "normalize_uploaded_video", fake_normalize, raising=False)
    monkeypatch.setattr(tasks, "transcribe_video_file", fake_transcribe, raising=False)

    await tasks._download_video_task(video.id)
    await db_session.refresh(video)

    assert video.local_path and video.local_path.endswith("source.mp4")
    assert video.duration_seconds == 130
    assert video.transcript_text == "hola mundo"
    assert video.transcript_language == "es"
    assert video.upload_original_path is None


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


async def test_render_clips_task_enqueues_jobs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = Video(
        id=50,
        source_url="https://youtube.com/watch?v=fanout",
        status=VideoStatus.PROCESSING.value,
        local_path=str(tmp_path / "vid.mp4"),
    )
    video.duration_seconds = 60
    clip1 = Clip(video_id=video.id, start_sec=0, end_sec=10, status=ClipStatus.RENDERING.value)
    clip2 = Clip(video_id=video.id, start_sec=10, end_sec=20, status=ClipStatus.RENDERING.value)
    db_session.add_all([video, clip1, clip2])
    await db_session.commit()
    monkeypatch.setattr(
        render_workspace.settings, "MEDIA_STORAGE_DIR", str(tmp_path / "media"), raising=False
    )

    sent: list[tuple[int, int, str]] = []

    def fake_send(video_id: int, clip_id: int, batch_id: str) -> None:
        sent.append((video_id, clip_id, batch_id))

    monkeypatch.setattr(tasks.render_clip_job, "send", fake_send)

    await tasks._render_clips_task(video.id)

    assert len(sent) == 2
    assert {clip_id for _, clip_id, _ in sent} == {clip1.id, clip2.id}


async def test_render_clip_job_marks_ready(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = Video(
        id=100,
        source_url="https://youtube.com/watch?v=render",
        status=VideoStatus.PROCESSING.value,
        local_path=str(tmp_path / "video.mp4"),
        render_batch_id="batch",
    )
    video.duration_seconds = 90
    clip = Clip(
        video_id=video.id,
        start_sec=0,
        end_sec=30,
        status=ClipStatus.RENDERING.value,
    )
    db_session.add_all([video, clip])
    await db_session.commit()
    monkeypatch.setattr(
        render_workspace.settings, "MEDIA_STORAGE_DIR", str(tmp_path / "media"), raising=False
    )

    def fake_render(*_: object, **__: object) -> ClipRenderResult:
        workspace = render_workspace.get_video_workspace(video.id)
        paths = workspace.clip_paths(clip.id)
        paths.final_path.parent.mkdir(parents=True, exist_ok=True)
        paths.final_path.write_bytes(b"bytes")
        return ClipRenderResult(
            final_path=paths.final_path,
            public_url=paths.public_url,
            width=1080,
            height=1920,
            frame_rate=30.0,
            file_size_bytes=paths.final_path.stat().st_size,
        )

    monkeypatch.setattr(tasks, "render_clip", fake_render, raising=False)
    finalize_called: list[int] = []
    monkeypatch.setattr(tasks.finalize_video, "send", lambda vid: finalize_called.append(vid))

    await tasks._render_clip_job(video.id, clip.id, "batch", enqueue_finalize=True)

    await db_session.refresh(video)
    await db_session.refresh(clip)
    assert clip.status == ClipStatus.READY.value
    assert clip.local_path is not None
    assert video.render_batch_id is None
    assert finalize_called == [video.id]


async def test_render_clip_job_handles_errors(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = Video(
        id=200,
        source_url="https://youtube.com/watch?v=err",
        status=VideoStatus.PROCESSING.value,
        local_path=str(tmp_path / "video.mp4"),
        render_batch_id="batch",
    )
    video.duration_seconds = 45
    clip = Clip(
        video_id=video.id,
        start_sec=5,
        end_sec=15,
        status=ClipStatus.RENDERING.value,
    )
    db_session.add_all([video, clip])
    await db_session.commit()
    monkeypatch.setattr(
        render_workspace.settings, "MEDIA_STORAGE_DIR", str(tmp_path / "media"), raising=False
    )

    def fail_render(*_: object, **__: object) -> ClipRenderResult:
        raise ClipRenderError("ffmpeg broken")

    monkeypatch.setattr(tasks, "render_clip", fail_render, raising=False)

    await tasks._render_clip_job(video.id, clip.id, "batch", enqueue_finalize=True)

    await db_session.refresh(video)
    await db_session.refresh(clip)
    assert video.status == VideoStatus.ERROR.value
    assert clip.status == ClipStatus.ERROR.value


async def test_render_clip_job_uses_thread_pool(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = Video(
        id=300,
        source_url="https://youtube.com/watch?v=thread",
        status=VideoStatus.PROCESSING.value,
        local_path=str(tmp_path / "video.mp4"),
        render_batch_id="batch",
    )
    video.duration_seconds = 60
    clip = Clip(
        video_id=video.id,
        start_sec=0,
        end_sec=30,
        status=ClipStatus.RENDERING.value,
    )
    db_session.add_all([video, clip])
    await db_session.commit()
    monkeypatch.setattr(
        render_workspace.settings, "MEDIA_STORAGE_DIR", str(tmp_path / "media"), raising=False
    )

    def fake_render(*_: object, **__: object) -> ClipRenderResult:
        workspace = render_workspace.get_video_workspace(video.id)
        paths = workspace.clip_paths(clip.id)
        paths.final_path.parent.mkdir(parents=True, exist_ok=True)
        paths.final_path.write_bytes(b"clip")
        return ClipRenderResult(
            final_path=paths.final_path,
            public_url=paths.public_url,
            width=1080,
            height=1920,
            frame_rate=30.0,
            file_size_bytes=paths.final_path.stat().st_size,
        )

    monkeypatch.setattr(tasks, "render_clip", fake_render, raising=False)

    called = False

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        return func(*args, **kwargs)

    monkeypatch.setattr(tasks.asyncio, "to_thread", fake_to_thread, raising=False)

    await tasks._render_clip_job(video.id, clip.id, "batch", enqueue_finalize=False)
    assert called


async def test_render_clip_jobs_respect_semaphore(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = Video(
        id=310,
        source_url="https://youtube.com/watch?v=semaphore",
        status=VideoStatus.PROCESSING.value,
        local_path=str(tmp_path / "video.mp4"),
        render_batch_id="batch",
    )
    video.duration_seconds = 90
    clip_a = Clip(video_id=video.id, start_sec=0, end_sec=30, status=ClipStatus.RENDERING.value)
    clip_b = Clip(video_id=video.id, start_sec=30, end_sec=60, status=ClipStatus.RENDERING.value)
    db_session.add_all([video, clip_a, clip_b])
    await db_session.commit()
    monkeypatch.setattr(
        render_workspace.settings, "MEDIA_STORAGE_DIR", str(tmp_path / "media"), raising=False
    )

    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    def fake_render(*args: object, **_kwargs: object) -> ClipRenderResult:
        workspace = render_workspace.get_video_workspace(video.id)
        clip_snapshot = cast(Clip, args[1])
        paths = workspace.clip_paths(clip_snapshot.id)  # type: ignore[arg-type]
        paths.final_path.parent.mkdir(parents=True, exist_ok=True)
        paths.final_path.write_bytes(b"bytes")

        if not first_started.is_set():
            first_started.set()
            release_first.wait()
        else:
            second_started.set()

        return ClipRenderResult(
            final_path=paths.final_path,
            public_url=paths.public_url,
            width=1080,
            height=1920,
            frame_rate=30.0,
            file_size_bytes=paths.final_path.stat().st_size,
        )

    monkeypatch.setattr(tasks, "render_clip", fake_render, raising=False)

    task_one = asyncio.create_task(
        tasks._render_clip_job(video.id, clip_a.id, "batch", enqueue_finalize=False)
    )
    task_two = asyncio.create_task(
        tasks._render_clip_job(video.id, clip_b.id, "batch", enqueue_finalize=False)
    )

    try:
        await asyncio.wait_for(asyncio.to_thread(first_started.wait), timeout=1)
        await asyncio.sleep(0.1)
        assert not second_started.is_set()
    finally:
        release_first.set()

    await asyncio.gather(task_one, task_two)
    assert second_started.is_set()


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
