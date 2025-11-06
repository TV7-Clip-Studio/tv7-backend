from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Raised when video download fails."""


class VideoTooLargeError(DownloadError):
    """Raised when video exceeds maximum file size."""


@dataclass(slots=True)
class DownloadResult:
    """Result of downloading a YouTube video."""

    local_path: str
    file_size_bytes: int
    transcript_text: str | None
    duration_seconds: int


def _extract_video_id(youtube_url: str) -> str:
    """Extract video ID from YouTube URL."""
    # yt-dlp can handle this, but we extract for transcript API
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"(?:embed\/)([0-9A-Za-z_-]{11})",
        r"^([0-9A-Za-z_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, youtube_url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from URL: {youtube_url}")


def _fetch_transcript(video_id: str) -> str | None:
    """Fetch transcript for a YouTube video."""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)  # type: ignore[attr-defined]

        # Try to get manual transcript first
        try:
            transcript = transcript_list.find_manually_created_transcript(["en"])
        except NoTranscriptFound:
            # Fall back to auto-generated
            try:
                transcript = transcript_list.find_generated_transcript(["en"])
            except NoTranscriptFound:
                logger.warning(
                    "No English transcript found",
                    extra={"video_id": video_id},
                )
                return None

        # Fetch and concatenate transcript segments
        segments = transcript.fetch()
        text = " ".join(segment["text"] for segment in segments)
        return text

    except (TranscriptsDisabled, VideoUnavailable) as exc:
        logger.warning(
            "Transcript unavailable",
            extra={"video_id": video_id, "error": str(exc)},
        )
        return None
    except Exception as exc:
        logger.exception(
            "Unexpected error fetching transcript",
            extra={"video_id": video_id, "error": str(exc)},
        )
        return None


def download_video_and_transcript(video_id: int, source_url: str) -> DownloadResult:
    """
    Download YouTube video and transcript.

    Args:
        video_id: Database video ID for organizing storage
        source_url: YouTube video URL

    Returns:
        DownloadResult with local path, file size, transcript, and duration

    Raises:
        DownloadError: If download fails
        VideoTooLargeError: If video exceeds MAX_VIDEO_FILE_SIZE_MB
    """
    # Create storage directory
    storage_dir = Path(settings.MEDIA_STORAGE_DIR) / "videos" / str(video_id)
    storage_dir.mkdir(parents=True, exist_ok=True)

    output_path = storage_dir / "source.mp4"

    # Configure yt-dlp options
    max_file_size = settings.MAX_VIDEO_FILE_SIZE_MB * 1024 * 1024  # Convert to bytes

    ydl_opts = {
        "format": "best[height<=720][ext=mp4]/best[ext=mp4]/best",
        "outtmpl": str(output_path),
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "max_filesize": max_file_size,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(
                "Starting video download",
                extra={"video_id": video_id, "source_url": source_url},
            )

            # Download video
            info = ydl.extract_info(source_url, download=True)

            if not info:
                raise DownloadError("Failed to extract video information")

            duration = int(info.get("duration", 0))

            # Check file size
            if not output_path.exists():
                raise DownloadError(f"Download completed but file not found at {output_path}")

            file_size = output_path.stat().st_size

            if file_size > max_file_size:
                # Clean up the file
                output_path.unlink()
                raise VideoTooLargeError(
                    f"Video size ({file_size / 1024 / 1024:.1f} MB) "
                    f"exceeds limit ({settings.MAX_VIDEO_FILE_SIZE_MB} MB)"
                )

            logger.info(
                "Video downloaded successfully",
                extra={
                    "video_id": video_id,
                    "file_size_mb": file_size / 1024 / 1024,
                    "duration_seconds": duration,
                },
            )

    except yt_dlp.utils.DownloadError as exc:
        logger.exception(
            "yt-dlp download failed",
            extra={"video_id": video_id, "source_url": source_url, "error": str(exc)},
        )
        # Clean up partial download
        if output_path.exists():
            output_path.unlink()
        raise DownloadError(f"Video download failed: {exc}") from exc

    except Exception as exc:
        logger.exception(
            "Unexpected error during download",
            extra={"video_id": video_id, "source_url": source_url, "error": str(exc)},
        )
        # Clean up partial download
        if output_path.exists():
            output_path.unlink()
        raise DownloadError(f"Unexpected download error: {exc}") from exc

    # Fetch transcript
    try:
        yt_video_id = _extract_video_id(source_url)
        transcript = _fetch_transcript(yt_video_id)
    except Exception as exc:
        logger.warning(
            "Failed to fetch transcript, continuing without it",
            extra={"video_id": video_id, "error": str(exc)},
        )
        transcript = None

    return DownloadResult(
        local_path=str(output_path),
        file_size_bytes=file_size,
        transcript_text=transcript,
        duration_seconds=duration,
    )
