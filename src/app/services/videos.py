from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.db.models import Clip, ClipStatus, Video
from app.repositories.videos import VideoRepository


@dataclass(slots=True)
class ClipSummary:
    total: int
    counts: dict[str, int]
    latest_updated_at: datetime | None

    def count(self, status: str) -> int:
        return self.counts.get(status, 0)

    @property
    def ready(self) -> int:
        return self.count(ClipStatus.READY.value)

    @property
    def rendering(self) -> int:
        return self.count(ClipStatus.RENDERING.value)

    @property
    def published(self) -> int:
        return self.count(ClipStatus.PUBLISHED_PARTIAL.value) + self.count(
            ClipStatus.PUBLISHED_ALL.value
        )

    @property
    def errored(self) -> int:
        return self.count(ClipStatus.ERROR.value)


@dataclass(slots=True)
class VideoDashboardEntry:
    video: Video
    clips: ClipSummary


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


async def get_video_detail(repo: VideoRepository, video_id: int) -> VideoDashboardEntry | None:
    """Return a single video with clip summary for the detail view."""
    video = await repo.get_with_clips(video_id)
    if not video:
        return None
    return VideoDashboardEntry(video=video, clips=_summarize_clips(video.clips))


async def list_videos(repo: VideoRepository) -> list[VideoDashboardEntry]:
    """Return dashboard-friendly summaries ordered by newest video first."""

    videos = await repo.list_with_clips()
    return [
        VideoDashboardEntry(video=video, clips=_summarize_clips(video.clips)) for video in videos
    ]
