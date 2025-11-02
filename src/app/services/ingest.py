from __future__ import annotations

import logging

from app.services.tasks import process_video

logger = logging.getLogger(__name__)


async def enqueue_video(video_id: int, *, source_url: str) -> None:
    """Dispatch a background job to process the video pipeline."""

    logger.info("Queueing video for processing", extra={"video_id": video_id, "url": source_url})
    process_video.send(video_id)
