from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from app.db.models import Clip, ClipStatus, Video, VideoStatus
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


@dataclass(slots=True)
class ClipSummary:
    total: int
    counts: dict[str, int]
    latest_updated_at: datetime | None

    def count(self, status: ClipStatus | str) -> int:
        key = status.value if isinstance(status, ClipStatus) else str(status)
        return self.counts.get(key, 0)

    @property
    def ready(self) -> int:
        return self.count(ClipStatus.READY)

    @property
    def rendering(self) -> int:
        return self.count(ClipStatus.RENDERING)

    @property
    def published(self) -> int:
        return self.count(ClipStatus.PUBLISHED_PARTIAL) + self.count(ClipStatus.PUBLISHED_ALL)

    @property
    def errored(self) -> int:
        return self.count(ClipStatus.ERROR)


@dataclass(slots=True)
class VideoDashboardEntry:
    video: Video
    clips: ClipSummary


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


def _summarize_clips(clips: Iterable[Clip]) -> ClipSummary:
    counts: Counter = Counter()
    latest_updated: datetime | None = None

    for clip in clips:
        counts[clip.status] += 1
        if clip.updated_at and (latest_updated is None or clip.updated_at > latest_updated):
            latest_updated = clip.updated_at

    for status in ClipStatus:
        counts.setdefault(status.value, 0)

    return ClipSummary(
        total=sum(counts.values()),
        counts=dict(counts),
        latest_updated_at=latest_updated,
    )


async def list_videos(repo: VideoRepository) -> list[VideoDashboardEntry]:
    """Return dashboard-friendly summaries ordered by newest video first."""

    videos = await repo.list_with_clips()
    return [
        VideoDashboardEntry(video=video, clips=_summarize_clips(video.clips)) for video in videos
    ]
