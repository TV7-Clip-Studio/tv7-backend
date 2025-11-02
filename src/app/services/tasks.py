from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

from dramatiq import actor

from app.db.base import session_scope
from app.db.models import Video, VideoStatus
from app.services.queue import ensure_broker

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


@actor(max_retries=3)
def process_video(video_id: int) -> None:
    """Entry point for the pipeline: mark video processing and kick off stages."""

    logger.info("Process video", extra={"video_id": video_id})
    _run_async(_set_video_status(video_id, VideoStatus.PROCESSING))
    download_video.send(video_id)


@actor(max_retries=3)
def download_video(video_id: int) -> None:
    """Download placeholder. Will be replaced with youtube_downloader integration."""

    logger.info("Download video (stub)", extra={"video_id": video_id})
    detect_highlights.send(video_id)


@actor(max_retries=3)
def detect_highlights(video_id: int) -> None:
    """Highlight detector placeholder. Will create clips once implemented."""

    logger.info("Detect highlights (stub)", extra={"video_id": video_id})
    finalize_video.send(video_id)


@actor(max_retries=3)
def finalize_video(video_id: int) -> None:
    """Complete the pipeline (stub) by marking the video ready."""

    logger.info("Finalize video", extra={"video_id": video_id})
    _run_async(_set_video_status(video_id, VideoStatus.READY))
