from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Coroutine
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any, TypeVar, cast

from dramatiq import actor
from dramatiq.middleware import CurrentMessage
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.db.base import session_scope
from app.db.models import Clip, ClipGenerationMode, ClipStatus, Video, VideoStatus
from app.repositories.youtube_credentials import YouTubeCredentialRepository
from app.services.clipper import ClipRenderError, render_clip
from app.services.highlight_detector import HighlightDetectionError
from app.services.highlight_detector import detect_highlights as detect_highlights_service
from app.services.queue import get_broker
from app.services.render_workspace import get_video_workspace
from app.services.youtube_downloader import (
    DownloadError,
    VideoTooLargeError,
    download_video_and_transcript,
)
from app.services.youtube_oauth import get_valid_access_token

logger = logging.getLogger(__name__)
_broker = get_broker()
_loop_lock = threading.Lock()
_worker_loop: asyncio.AbstractEventLoop | None = None
_render_semaphore = threading.Semaphore(max(1, settings.CLIP_RENDER_MAX_PARALLEL))
T = TypeVar("T")


def _ensure_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop  # noqa: PLW0603
    if _worker_loop is not None:
        return _worker_loop
    with _loop_lock:
        if _worker_loop is None:
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name="dramatiq-worker-loop", daemon=True
            )
            thread.start()
            _worker_loop = loop
    return _worker_loop


def _run_async(coro: Coroutine[Any, Any, T]) -> T:  # noqa: UP047
    """Execute an async coroutine on the shared worker event loop."""

    loop = _ensure_worker_loop()
    future: Future[T] = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def _current_message_id(fallback: str | None = None) -> str:
    try:
        current_message = CurrentMessage.get_current_message()
        if current_message is None:
            raise LookupError
        return cast(str, current_message.message_id)
    except Exception:
        return fallback or uuid.uuid4().hex


async def _set_video_status(video_id: int, status: VideoStatus) -> None:
    async with session_scope() as session:
        video = await session.get(Video, video_id)
        if not video:
            logger.warning("Video missing while updating status", extra={"video_id": video_id})
            return

        video.status = status.value
        await session.flush()


async def _get_video(video_id: int) -> Video | None:
    async with session_scope() as session:
        video: Video | None = await session.get(Video, video_id)
        return video


async def _get_video_status(video_id: int) -> VideoStatus | None:
    video = await _get_video(video_id)
    if not video:
        return None
    return VideoStatus(video.status)


async def _video_has_error(video_id: int) -> bool:
    status = await _get_video_status(video_id)
    return status == VideoStatus.ERROR


@actor(broker=_broker, max_retries=3)
def process_video(video_id: int, message_id: str | None = None) -> None:
    """Entry point for the pipeline: mark video processing and kick off stages."""

    # Get current message ID from Dramatiq context
    msg_id = _current_message_id(message_id or "unknown")

    logger.info(
        "Process video",
        extra={"video_id": video_id, "task_id": msg_id},
    )
    _run_async(_set_video_status(video_id, VideoStatus.PROCESSING))
    download_video.send(video_id)


async def _download_video_task(video_id: int) -> None:
    """Download video and update database with results."""
    async with session_scope() as session:
        video = await session.get(Video, video_id)
        if not video:
            logger.error("Video not found for download", extra={"video_id": video_id})
            return

        workspace = get_video_workspace(video_id)
        video.workspace_root = str(workspace.root)

        access_token: str | None = None
        if video.requested_by_user_id:
            credential_repo = YouTubeCredentialRepository(session)
            try:
                access_token = await get_valid_access_token(
                    video.requested_by_user_id, credential_repo
                )
            except Exception as exc:  # pragma: no cover - network errors
                logger.warning(
                    "Failed to refresh YouTube access token",
                    extra={"video_id": video_id, "error": str(exc)},
                )

        try:
            append_mode = video.clip_generation_mode == ClipGenerationMode.APPEND.value
            if (
                append_mode
                and video.local_path
                and video.transcript_text
                and video.duration_seconds
            ):
                logger.info(
                    "Skipping video download; reusing cached assets",
                    extra={"video_id": video_id},
                )
                return
            # Download video and transcript
            result = download_video_and_transcript(
                video_id,
                video.source_url,
                access_token=access_token,
            )

            # Update video with download results
            video.local_path = result.local_path
            video.file_size_bytes = result.file_size_bytes
            video.transcript_text = result.transcript_text
            video.transcript_language = result.transcript_language
            video.duration_seconds = result.duration_seconds
            video.error_message = None  # Clear any previous errors

            await session.flush()

            logger.info(
                "Video downloaded successfully",
                extra={
                    "video_id": video_id,
                    "duration": result.duration_seconds,
                    "file_size_mb": result.file_size_bytes / 1024 / 1024,
                    "has_transcript": result.transcript_text is not None,
                },
            )

        except VideoTooLargeError as exc:
            logger.warning(
                "Video too large",
                extra={"video_id": video_id, "error": str(exc)},
            )
            video.status = VideoStatus.ERROR.value
            video.error_message = str(exc)
            await session.flush()

        except DownloadError as exc:
            logger.error(
                "Video download failed",
                extra={"video_id": video_id, "error": str(exc)},
            )
            video.status = VideoStatus.ERROR.value
            video.error_message = str(exc)
            await session.flush()

        except Exception as exc:
            logger.exception(
                "Unexpected error downloading video",
                extra={"video_id": video_id, "error": str(exc)},
            )
            video.status = VideoStatus.ERROR.value
            video.error_message = f"Unexpected error: {exc}"
            await session.flush()


@actor(broker=_broker, max_retries=3)
def download_video(video_id: int) -> None:
    """Download YouTube video and transcript."""

    msg_id = _current_message_id()

    logger.info(
        "Starting video download",
        extra={"video_id": video_id, "task_id": msg_id},
    )
    _run_async(_download_video_task(video_id))

    # Only continue to next stage if download succeeded
    # Check video status to determine if we should proceed
    async def _should_continue() -> bool:
        async with session_scope() as session:
            video = await session.get(Video, video_id)
            return video is not None and video.status != VideoStatus.ERROR.value

    if _run_async(_should_continue()):
        detect_highlights.send(video_id)
    else:
        logger.warning(
            "Skipping highlight detection due to download error",
            extra={"video_id": video_id, "task_id": msg_id},
        )


async def _detect_highlights_task(video_id: int) -> None:
    """Detect highlights using LLM and create Clip records."""
    async with session_scope() as session:
        video = await session.get(Video, video_id)
        if not video:
            logger.error("Video not found for highlight detection", extra={"video_id": video_id})
            return

        try:
            # Check if we have required data
            if not video.transcript_text:
                raise HighlightDetectionError("No transcript available for highlight detection")

            if not video.duration_seconds:
                raise HighlightDetectionError("Video duration not available")

            append_mode = video.clip_generation_mode == ClipGenerationMode.APPEND.value
            if not append_mode:
                await session.execute(delete(Clip).where(Clip.video_id == video_id))

            # Call LLM to detect highlights
            segments = await detect_highlights_service(
                transcript=video.transcript_text,
                duration_seconds=video.duration_seconds,
                video_id=video_id,
                transcript_language=video.transcript_language,
            )

            # Create Clip records for each segment
            clip_ids = []
            for segment in segments:
                clip = Clip(
                    video_id=video_id,
                    start_sec=segment.start_sec,
                    end_sec=segment.end_sec,
                    caption_text=segment.hook,
                    status=ClipStatus.RENDERING.value,
                )
                session.add(clip)
                await session.flush()  # Flush to get clip ID
                clip_ids.append(clip.id)

            video.clip_generation_mode = ClipGenerationMode.REPLACE.value
            await session.flush()

            logger.info(
                "Clips created successfully",
                extra={
                    "video_id": video_id,
                    "clip_count": len(segments),
                    "clip_ids": clip_ids,
                },
            )

        except HighlightDetectionError as exc:
            logger.error(
                "Highlight detection failed",
                extra={"video_id": video_id, "error": str(exc)},
            )
            video.status = VideoStatus.ERROR.value
            video.error_message = f"Highlight detection failed: {exc}"
            video.clip_generation_mode = ClipGenerationMode.REPLACE.value
            await session.flush()

        except Exception as exc:
            logger.exception(
                "Unexpected error during highlight detection",
                extra={"video_id": video_id, "error": str(exc)},
            )
            video.status = VideoStatus.ERROR.value
            video.error_message = f"Unexpected error during highlight detection: {exc}"
            video.clip_generation_mode = ClipGenerationMode.REPLACE.value
            await session.flush()


@actor(broker=_broker, max_retries=3)
def detect_highlights(video_id: int) -> None:
    """Detect highlights using LLM and create Clip records."""

    msg_id = _current_message_id()

    logger.info(
        "Starting highlight detection",
        extra={"video_id": video_id, "task_id": msg_id},
    )
    _run_async(_detect_highlights_task(video_id))

    # Only continue to next stage if highlight detection succeeded
    async def _should_continue() -> bool:
        async with session_scope() as session:
            video = await session.get(Video, video_id)
            return video is not None and video.status != VideoStatus.ERROR.value

    if _run_async(_should_continue()):
        render_clips.send(video_id)
    else:
        logger.warning(
            "Skipping finalization due to highlight detection error",
            extra={"video_id": video_id, "task_id": msg_id},
        )


async def _prepare_render_batch(video_id: int) -> tuple[str, list[int]] | None:
    async with session_scope() as session:
        video = await session.get(Video, video_id)
        if not video:
            logger.error("Video not found for rendering", extra={"video_id": video_id})
            return None

        if not video.local_path:
            video.status = VideoStatus.ERROR.value
            video.error_message = "Video missing local_path for rendering"
            await session.flush()
            return None

        result = await session.execute(
            select(Clip).where(Clip.video_id == video_id).order_by(Clip.start_sec)
        )
        clips = result.scalars().all()
        if not clips:
            logger.warning("No clips to render", extra={"video_id": video_id})
            return None

        batch_id = uuid.uuid4().hex
        video.render_batch_id = batch_id
        for clip in clips:
            if clip.status != ClipStatus.READY.value:
                clip.status = ClipStatus.RENDERING.value
        await session.flush()
        return batch_id, [clip.id for clip in clips]


async def _render_clips_task(video_id: int) -> None:
    batch = await _prepare_render_batch(video_id)
    if not batch:
        return
    batch_id, clip_ids = batch
    logger.info(
        "Dispatching render batch",
        extra={"video_id": video_id, "batch_id": batch_id, "clip_ids": clip_ids},
    )
    for clip_id in clip_ids:
        render_clip_job.send(video_id, clip_id, batch_id)


async def _render_clip_job(
    video_id: int,
    clip_id: int,
    batch_id: str,
    *,
    enqueue_finalize: bool = True,
) -> None:
    async with session_scope() as session:
        video = await session.get(Video, video_id)
        clip_state = await session.get(Clip, clip_id)
        if not video or not clip_state or video.render_batch_id != batch_id:
            return
        workspace = get_video_workspace(video_id)
        video_snapshot = cast(
            Video,
            SimpleNamespace(
                id=video.id,
                local_path=video.local_path,
                duration_seconds=video.duration_seconds,
            ),
        )
        clip_snapshot = cast(
            Clip,
            SimpleNamespace(
                id=clip_state.id,
                video_id=clip_state.video_id,
                start_sec=clip_state.start_sec,
                end_sec=clip_state.end_sec,
                status=clip_state.status,
            ),
        )
        overwrite_existing = clip_state.status != ClipStatus.READY.value

    def _render_with_semaphore() -> Any:
        with _render_semaphore:
            return render_clip(
                video_snapshot,
                clip_snapshot,
                workspace,
                overwrite=overwrite_existing,
            )

    try:
        clip_result = await asyncio.to_thread(_render_with_semaphore)
    except ClipRenderError as exc:
        async with session_scope() as session:
            video = await session.get(Video, video_id)
            clip = await session.get(Clip, clip_id)
            if not video or video.render_batch_id != batch_id or not clip:
                return
            clip.status = ClipStatus.ERROR.value
            video.status = VideoStatus.ERROR.value
            video.error_message = f"Clip {clip_id} render failed: {exc}"
            video.render_batch_id = None
            await session.flush()
        return

    async with session_scope() as session:
        video = await session.get(Video, video_id)
        clip = await session.get(Clip, clip_id)
        if not video or not clip or video.render_batch_id != batch_id:
            return

        clip.local_path = clip_result.public_url
        clip.render_width = clip_result.width
        clip.render_height = clip_result.height
        clip.frame_rate = clip_result.frame_rate
        clip.file_size_bytes = clip_result.file_size_bytes
        clip.status = ClipStatus.READY.value
        await session.flush()

    completed = await _maybe_finalize_video(video_id, batch_id, enqueue_finalize=enqueue_finalize)
    if completed and not enqueue_finalize:
        await _set_video_status(video_id, VideoStatus.READY)


async def _maybe_finalize_video(
    video_id: int,
    batch_id: str,
    *,
    enqueue_finalize: bool = True,
) -> bool:
    async with session_scope() as session:
        video = await session.get(Video, video_id)
        if not video or video.render_batch_id != batch_id:
            return False
        remaining = await session.scalar(
            select(func.count()).where(
                Clip.video_id == video_id, Clip.status != ClipStatus.READY.value
            )
        )
        if remaining and remaining > 0:
            return False
        video.render_batch_id = None
        await session.flush()

    if enqueue_finalize:
        finalize_video.send(video_id)
    return True


@actor(broker=_broker, max_retries=3)
def render_clips(video_id: int) -> None:
    msg_id = _current_message_id()
    logger.info(
        "Rendering clips",
        extra={"video_id": video_id, "task_id": msg_id},
    )
    _run_async(_render_clips_task(video_id))


@actor(broker=_broker, max_retries=3)
def render_clip_job(video_id: int, clip_id: int, batch_id: str) -> None:
    msg_id = _current_message_id(f"batch-{batch_id}")
    logger.info(
        "Rendering clip job",
        extra={"video_id": video_id, "clip_id": clip_id, "batch_id": batch_id, "task_id": msg_id},
    )
    _run_async(_render_clip_job(video_id, clip_id, batch_id))


@actor(broker=_broker, max_retries=3)
def finalize_video(video_id: int) -> None:
    """Complete the pipeline (stub) by marking the video ready."""

    msg_id = _current_message_id()

    logger.info(
        "Finalize video",
        extra={"video_id": video_id, "task_id": msg_id},
    )
    _run_async(_set_video_status(video_id, VideoStatus.READY))


async def run_pipeline_inline(video_id: int) -> None:
    """
    Execute the full pipeline sequentially inside the API process.

    Used when the Dramatiq stub broker is configured, ensuring local/dev
    environments advance Video status without a background worker.
    """

    logger.info("Running inline pipeline", extra={"video_id": video_id})
    await _set_video_status(video_id, VideoStatus.PROCESSING)
    await _download_video_task(video_id)

    if await _video_has_error(video_id):
        logger.warning("Inline pipeline halted after download", extra={"video_id": video_id})
        return

    await _detect_highlights_task(video_id)

    if await _video_has_error(video_id):
        logger.warning(
            "Inline pipeline halted after highlight detection", extra={"video_id": video_id}
        )
        return

    batch = await _prepare_render_batch(video_id)
    if not batch:
        logger.warning("Inline pipeline halted during render prep", extra={"video_id": video_id})
        return

    batch_id, clip_ids = batch
    for clip_id in clip_ids:
        await _render_clip_job(video_id, clip_id, batch_id, enqueue_finalize=False)
        if await _video_has_error(video_id):
            logger.warning("Inline pipeline halted during rendering", extra={"video_id": video_id})
            return

    logger.info("Inline pipeline completed", extra={"video_id": video_id})
