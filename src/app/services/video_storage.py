from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def ensure_video_storage(video_id: int) -> Path:
    """
    Ensure the base directory for a video's artifacts exists and return it.

    All normalized uploads and downloaded sources live under
    MEDIA_STORAGE_DIR/videos/<video_id>.
    """

    storage_dir = Path(settings.MEDIA_STORAGE_DIR) / "videos" / str(video_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def source_paths(video_id: int) -> tuple[Path, Path, Path]:
    """
    Return the storage directory, yt-dlp outtmpl, and final source path.
    """

    storage_dir = ensure_video_storage(video_id)
    output_template = storage_dir / "source.%(ext)s"
    final_output_path = storage_dir / "source.mp4"
    return storage_dir, output_template, final_output_path
