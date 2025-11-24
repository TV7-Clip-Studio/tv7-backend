from __future__ import annotations

import subprocess  # nosec B404
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.services.video_storage import ensure_video_storage


class VideoNormalizationError(Exception):
    """Raised when ffmpeg cannot normalize the uploaded video."""


@dataclass(slots=True)
class VideoNormalizationResult:
    normalized_path: str
    file_size_bytes: int
    duration_seconds: int


def _ffprobe_duration_seconds(path: Path) -> int:
    cmd = [
        settings.FFPROBE_BIN,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.UPLOAD_NORMALIZATION_TIMEOUT_SECONDS,
        )  # nosec B603
    except subprocess.TimeoutExpired as exc:
        raise VideoNormalizationError(
            f"ffprobe timed out after {settings.UPLOAD_NORMALIZATION_TIMEOUT_SECONDS}s"
        ) from exc
    except FileNotFoundError as exc:  # pragma: no cover
        raise VideoNormalizationError(f"ffprobe not found: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise VideoNormalizationError(f"ffprobe failed: {exc.stderr}") from exc

    raw = (completed.stdout or "").strip()
    if not raw:
        raise VideoNormalizationError("Unable to detect video duration")
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise VideoNormalizationError(f"Invalid duration value: {raw}") from exc
    return int(seconds)


def normalize_uploaded_video(video_id: int, source_path: Path) -> VideoNormalizationResult:
    """
    Normalize an uploaded video to the canonical storage profile.

    Returns the path to the normalized mp4 that the pipeline can consume.
    """

    if not source_path.exists():
        raise VideoNormalizationError("Original upload missing from disk")

    storage_dir = ensure_video_storage(video_id)
    temp_output = storage_dir / "source.normalized.tmp.mp4"
    final_output = storage_dir / "source.mp4"

    scale_filter = f"scale=-2:min({settings.UPLOAD_NORMALIZED_MAX_HEIGHT}\\,ih)"
    cmd = [
        settings.FFMPEG_BIN,
        "-y",
        "-i",
        str(source_path),
        "-vf",
        scale_filter,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        settings.UPLOAD_NORMALIZED_VIDEO_BITRATE,
        "-c:a",
        "aac",
        "-b:a",
        settings.UPLOAD_NORMALIZED_AUDIO_BITRATE,
        str(temp_output),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.UPLOAD_NORMALIZATION_TIMEOUT_SECONDS,
        )  # nosec B603
    except subprocess.TimeoutExpired as exc:
        raise VideoNormalizationError(
            f"ffmpeg timed out after {settings.UPLOAD_NORMALIZATION_TIMEOUT_SECONDS}s"
        ) from exc
    except FileNotFoundError as exc:  # pragma: no cover
        raise VideoNormalizationError(f"ffmpeg not found: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "unknown error"
        raise VideoNormalizationError(stderr) from exc

    temp_output.replace(final_output)
    with suppress(FileNotFoundError):
        source_path.unlink()

    duration_seconds = _ffprobe_duration_seconds(final_output)
    file_size_bytes = final_output.stat().st_size

    return VideoNormalizationResult(
        normalized_path=str(final_output),
        file_size_bytes=file_size_bytes,
        duration_seconds=duration_seconds,
    )
