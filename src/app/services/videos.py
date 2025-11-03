from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from app.db.models import Video, VideoStatus
from app.repositories.videos import VideoRepository
from app.services.ingest import enqueue_video

logger = logging.getLogger(__name__)

YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


class InvalidYouTubeURL(ValueError):
    """Raised when an ingest request does not target a supported YouTube domain."""


@dataclass(slots=True)
class VideoIngestionResult:
    video: Video
    created: bool
    queued: bool = True


async def _default_dispatch(video_id: int, source_url: str) -> None:
    await enqueue_video(video_id, source_url=source_url)


async def ingest_video(
    youtube_url: str,
    repo: VideoRepository,
    *,
    task_dispatcher: Callable[[int, str], Awaitable[None]] | None = None,
) -> VideoIngestionResult:
    parsed = urlparse(youtube_url)
    if parsed.hostname not in YOUTUBE_DOMAINS:
        raise InvalidYouTubeURL("URL must point to YouTube")

    existing = await repo.get_by_source_url(youtube_url)
    created = False

    if existing:
        video = existing
        logger.info(
            "Video already ingested; re-queueing",
            extra={"video_id": video.id, "source_url": video.source_url},
        )
    else:
        video = Video(source_url=youtube_url, status=VideoStatus.INGESTED.value)
        await repo.add(video)
        video = await repo.refresh(video)
        created = True
        logger.info("Created new video record", extra={"video_id": video.id})

    dispatcher = task_dispatcher or _default_dispatch
    await dispatcher(video.id, video.source_url)
    video = await repo.refresh(video)

    return VideoIngestionResult(video=video, created=created)
