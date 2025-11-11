from __future__ import annotations

import logging

from dramatiq.brokers.stub import StubBroker

from app.services.queue import get_broker
from app.services.tasks import process_video, run_pipeline_inline

logger = logging.getLogger(__name__)


async def enqueue_video(video_id: int, *, source_url: str, user_id: int | None = None) -> None:
    """Dispatch a background job to process the video pipeline."""

    logger.info(
        "Queueing video for processing",
        extra={
            "video_id": video_id,
            "url": source_url,
            "user_id": user_id,
        },
    )
    # Ensure the actor is bound to the currently configured broker (docker vs. local).
    process_video.broker = get_broker()
    broker = process_video.broker

    if isinstance(broker, StubBroker):
        logger.info(
            "Running inline pipeline because stub broker is active",
            extra={
                "video_id": video_id,
                "user_id": user_id,
            },
        )
        await run_pipeline_inline(video_id)
        return

    process_video.send(video_id)
