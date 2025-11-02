from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def enqueue_video(video_id: int, *, source_url: str) -> None:
    """Placeholder for the background job pipeline.

    Once the background worker (roadmap item 1.3) exists, this function should
    dispatch a task that downloads the source video, extracts transcripts, runs
    highlight detection, renders clips, and updates database state. For now we
    simply log the intention so the ingest endpoint can return immediately.
    """

    # TODO(roadmap-1.3): replace with real task queue dispatch.
    logger.info("Enqueued video for processing", extra={"video_id": video_id, "url": source_url})
