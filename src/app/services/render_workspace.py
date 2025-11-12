from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

MEDIA_URL_PREFIX = "/media"


@dataclass(slots=True)
class ClipPaths:
    video_id: int
    clip_id: int
    final_path: Path
    public_url: str
    temp_dir: Path
    mezzanine_video: Path
    subtitles_file: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)


@dataclass(slots=True)
class VideoWorkspace:
    video_id: int
    root: Path
    source_dir: Path
    clips_dir: Path
    temp_dir: Path
    media_url_prefix: str = MEDIA_URL_PREFIX

    def ensure(self) -> VideoWorkspace:
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        return self

    def public_clip_url(self, clip_id: int, suffix: str) -> str:
        safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return f"{self.media_url_prefix}/clips/{self.video_id}/{clip_id}{safe_suffix}"

    def cleanup_clip(self, clip_id: int) -> None:
        shutil.rmtree(self.temp_dir / str(clip_id), ignore_errors=True)

    def clip_paths(self, clip_id: int, *, suffix: str = ".mp4") -> ClipPaths:
        safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        final_path = self.clips_dir / f"{clip_id}{safe_suffix}"
        clip_tmp = self.temp_dir / str(clip_id)
        clip_tmp.mkdir(parents=True, exist_ok=True)

        mezzanine_dir = clip_tmp / "mezzanine"
        subtitles_dir = clip_tmp / "subtitles"
        mezzanine_dir.mkdir(parents=True, exist_ok=True)
        subtitles_dir.mkdir(parents=True, exist_ok=True)

        mezzanine_video = mezzanine_dir / f"{clip_id}{safe_suffix}"
        subtitles_file = subtitles_dir / f"{clip_id}.vtt"

        return ClipPaths(
            video_id=self.video_id,
            clip_id=clip_id,
            final_path=final_path,
            public_url=self.public_clip_url(clip_id, safe_suffix),
            temp_dir=clip_tmp,
            mezzanine_video=mezzanine_video,
            subtitles_file=subtitles_file,
        )


def get_video_workspace(video_id: int) -> VideoWorkspace:
    media_root = Path(settings.MEDIA_STORAGE_DIR)
    root = media_root / "videos" / str(video_id)
    clips_dir = media_root / "clips" / str(video_id)
    temp_dir = media_root / "tmp" / str(video_id)
    workspace = VideoWorkspace(
        video_id=video_id,
        root=root,
        source_dir=root,
        clips_dir=clips_dir,
        temp_dir=temp_dir,
    )
    return workspace.ensure()
