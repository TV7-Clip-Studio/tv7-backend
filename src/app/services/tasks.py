from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

from dramatiq import actor

from app.db.base import session_scope
from app.db.models import Clip, ClipStatus, Video, VideoStatus
from app.services.highlight_detector import HighlightDetectionError
from app.services.highlight_detector import detect_highlights as detect_highlights_service
from app.services.queue import ensure_broker
from app.services.youtube_downloader import (
    DownloadError,
    VideoTooLargeError,
    download_video_and_transcript,
)

logger = logging.getLogger(__name__)

# Ensure broker configured when module is imported.
ensure_broker()


def _run_async(coro: Coroutine[None, None, None]) -> None:
    """Execute an async coroutine in a fresh event loop."""

    asyncio.run(coro)


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


@actor(max_retries=3)
def process_video(video_id: int) -> None:
    """Entry point for the pipeline: mark video processing and kick off stages."""

    logger.info("Process video", extra={"video_id": video_id})
    _run_async(_set_video_status(video_id, VideoStatus.PROCESSING))
    download_video.send(video_id)


async def _download_video_task(video_id: int) -> None:
    """Download video and update database with results."""
    async with session_scope() as session:
        video = await session.get(Video, video_id)
        if not video:
            logger.error("Video not found for download", extra={"video_id": video_id})
            return

        try:
            # Download video and transcript
            result = download_video_and_transcript(video_id, video.source_url)

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


@actor(max_retries=3)
def download_video(video_id: int) -> None:
    """Download YouTube video and transcript."""

    logger.info("Starting video download", extra={"video_id": video_id})
    _run_async(_download_video_task(video_id))

    # Only continue to next stage if download succeeded
    # Check video status to determine if we should proceed
    async def _should_continue() -> bool:
        async with session_scope() as session:
            video = await session.get(Video, video_id)
            return video is not None and video.status != VideoStatus.ERROR.value

    if asyncio.run(_should_continue()):
        detect_highlights.send(video_id)
    else:
        logger.warning(
            "Skipping highlight detection due to download error",
            extra={"video_id": video_id},
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

            # Call LLM to detect highlights
            segments = await detect_highlights_service(
                transcript=video.transcript_text,
                duration_seconds=video.duration_seconds,
                video_id=video_id,
                transcript_language=video.transcript_language,
            )

            # Create Clip records for each segment
            for segment in segments:
                clip = Clip(
                    video_id=video_id,
                    start_sec=segment.start_sec,
                    end_sec=segment.end_sec,
                    caption_text=segment.hook,
                    status=ClipStatus.RENDERING.value,
                )
                session.add(clip)

            await session.flush()

            logger.info(
                "Clips created successfully",
                extra={"video_id": video_id, "clip_count": len(segments)},
            )

        except HighlightDetectionError as exc:
            logger.error(
                "Highlight detection failed",
                extra={"video_id": video_id, "error": str(exc)},
            )
            video.status = VideoStatus.ERROR.value
            video.error_message = f"Highlight detection failed: {exc}"
            await session.flush()

        except Exception as exc:
            logger.exception(
                "Unexpected error during highlight detection",
                extra={"video_id": video_id, "error": str(exc)},
            )
            video.status = VideoStatus.ERROR.value
            video.error_message = f"Unexpected error during highlight detection: {exc}"
            await session.flush()


@actor(max_retries=3)
def detect_highlights(video_id: int) -> None:
    """Detect highlights using LLM and create Clip records."""

    logger.info("Starting highlight detection", extra={"video_id": video_id})
    _run_async(_detect_highlights_task(video_id))

    # Only continue to next stage if highlight detection succeeded
    async def _should_continue() -> bool:
        async with session_scope() as session:
            video = await session.get(Video, video_id)
            return video is not None and video.status != VideoStatus.ERROR.value

    if asyncio.run(_should_continue()):
        finalize_video.send(video_id)
    else:
        logger.warning(
            "Skipping finalization due to highlight detection error",
            extra={"video_id": video_id},
        )


@actor(max_retries=3)
def finalize_video(video_id: int) -> None:
    """Complete the pipeline (stub) by marking the video ready."""

    logger.info("Finalize video", extra={"video_id": video_id})
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

    await _set_video_status(video_id, VideoStatus.READY)
    logger.info("Inline pipeline completed", extra={"video_id": video_id})
