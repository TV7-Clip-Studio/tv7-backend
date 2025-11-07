from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, VideoUnavailable

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
    transcript_language: str | None
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


# Protocol typing fallback for mypy; at runtime we rely on youtube_transcript_api.Transcript.
class _Transcript(Protocol):
    language_code: str | None
    is_generated: bool

    def fetch(self) -> Iterable[dict[str, str]]: ...


PREFERRED_TRANSCRIPT_LANGS = ["en", "es", "pt", "fr", "de", "it", "ja", "ko"]


def _is_preferred_language(code: str | None) -> bool:
    if not code:
        return False
    normalized = code.lower()
    return any(
        normalized == lang or normalized.startswith(f"{lang}-")
        for lang in PREFERRED_TRANSCRIPT_LANGS
    )


def _fetch_transcript(video_id: str) -> tuple[str | None, str | None]:
    """Fetch transcript text plus detected language for a YouTube video."""
    api = YouTubeTranscriptApi()
    try:
        transcript_list = api.list(video_id)
        transcripts = cast(list[_Transcript], list(transcript_list))

        manual = [t for t in transcripts if not getattr(t, "is_generated", False)]
        generated = [t for t in transcripts if getattr(t, "is_generated", False)]

        def _pick(candidates: list[_Transcript]) -> _Transcript | None:
            for preferred in PREFERRED_TRANSCRIPT_LANGS:
                for transcript in candidates:
                    code = (transcript.language_code or "").lower()
                    if code == preferred or code.startswith(f"{preferred}-"):
                        return transcript
            return candidates[0] if candidates else None

        transcript = _pick(manual) or _pick(generated)

        if transcript is None:
            logger.warning("No transcript found", extra={"video_id": video_id})
            return None, None

        # Fetch and concatenate transcript segments
        segments = transcript.fetch()
        text = " ".join(segment["text"].strip() for segment in segments if segment["text"].strip())
        language = getattr(transcript, "language_code", None)
        return text or None, language

    except (TranscriptsDisabled, VideoUnavailable) as exc:
        logger.warning(
            "Transcript unavailable",
            extra={"video_id": video_id, "error": str(exc)},
        )
        return None, None
    except Exception as exc:
        logger.exception(
            "Unexpected error fetching transcript",
            extra={"video_id": video_id, "error": str(exc)},
        )
        return None, None


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

    output_template = storage_dir / "source.%(ext)s"
    final_output_path = storage_dir / "source.mp4"

    # Configure yt-dlp options
    max_file_size = settings.MAX_VIDEO_FILE_SIZE_MB * 1024 * 1024  # Convert to bytes

    ydl_opts = {
        "format": "bestvideo[height<=720]+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": str(output_template),
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "max_filesize": max_file_size,
        "prefer_ffmpeg": True,
        "postprocessors": [
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }
        ],
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

            # Ensure the final mp4 exists (postprocessing may rename files)
            if not final_output_path.exists():
                # If yt-dlp emitted another extension (e.g., .mkv) convert it manually
                for candidate in storage_dir.glob("source.*"):
                    if candidate != final_output_path:
                        candidate.rename(final_output_path)
                        break

            if not final_output_path.exists():
                raise DownloadError(f"Download completed but file not found at {final_output_path}")

            file_size = final_output_path.stat().st_size

            if file_size > max_file_size:
                # Clean up the file
                final_output_path.unlink()
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
        if final_output_path.exists():
            final_output_path.unlink()
        raise DownloadError(f"Video download failed: {exc}") from exc

    except Exception as exc:
        logger.exception(
            "Unexpected error during download",
            extra={"video_id": video_id, "source_url": source_url, "error": str(exc)},
        )
        # Clean up partial download
        if final_output_path.exists():
            final_output_path.unlink()
        raise DownloadError(f"Unexpected download error: {exc}") from exc

    # Fetch transcript
    transcript_language = None
    try:
        yt_video_id = _extract_video_id(source_url)
        transcript, transcript_language = _fetch_transcript(yt_video_id)
    except Exception as exc:
        logger.warning(
            "Failed to fetch transcript, continuing without it",
            extra={"video_id": video_id, "error": str(exc)},
        )
        transcript = None

    return DownloadResult(
        local_path=str(final_output_path),
        file_size_bytes=file_size,
        transcript_text=transcript,
        transcript_language=transcript_language,
        duration_seconds=duration,
    )
