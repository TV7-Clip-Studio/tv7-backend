from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from http import HTTPStatus
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Protocol, cast

import httpx
import yt_dlp
from requests import Session  # type: ignore[import]
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, VideoUnavailable

from app.core.config import settings

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Raised when video download fails."""


class VideoTooLargeError(DownloadError):
    """Raised when video exceeds maximum file size."""


class AuthenticationRequiredError(DownloadError):
    """Raised when YouTube requires authentication (age-restricted or sign-in required)."""


class FormatUnavailableError(DownloadError):
    """Raised when the requested format is not offered by the video."""


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
CAPTIONS_API_URL = "https://www.googleapis.com/youtube/v3/captions"
TRANSCRIPT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
CAPTIONS_FORBIDDEN_STATUS = HTTPStatus.FORBIDDEN


def _is_preferred_language(code: str | None) -> bool:
    if not code:
        return False
    normalized = code.lower()
    return any(
        normalized == lang or normalized.startswith(f"{lang}-")
        for lang in PREFERRED_TRANSCRIPT_LANGS
    )


def _fetch_transcript(
    video_id: str, access_token: str | None = None
) -> tuple[str | None, str | None]:
    """Fetch transcript text plus detected language for a YouTube video."""
    if access_token:
        text, language = _fetch_transcript_with_oauth(video_id, access_token)
        if text:
            return text, language
        logger.info(
            "OAuth transcript fetch unavailable; falling back to transcript API",
            extra={"video_id": video_id},
        )

    api = _build_transcript_api()
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
        text = " ".join(
            (
                getattr(segment, "text", "").strip()
                if not isinstance(segment, dict)
                else segment.get("text", "").strip()
            )
            for segment in segments
            if (
                getattr(segment, "text", "")
                if not isinstance(segment, dict)
                else segment.get("text", "")
            )
        ).strip()
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


def _prepare_storage_paths(video_id: int) -> tuple[Path, Path, Path]:
    storage_dir = Path(settings.MEDIA_STORAGE_DIR) / "videos" / str(video_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    output_template = storage_dir / "source.%(ext)s"
    final_output_path = storage_dir / "source.mp4"
    return storage_dir, output_template, final_output_path


def _apply_cookie_auth(ydl_opts: dict[str, object]) -> None:
    if settings.YOUTUBE_COOKIES_FILE:
        cookies_path = Path(settings.YOUTUBE_COOKIES_FILE)
        if cookies_path.exists():
            ydl_opts["cookiefile"] = str(cookies_path)
            logger.info(
                "Using cookies file for YouTube download",
                extra={"cookies_file": settings.YOUTUBE_COOKIES_FILE},
            )
        else:
            logger.warning(
                "Cookies file not found, downloading without authentication",
                extra={"cookies_file": settings.YOUTUBE_COOKIES_FILE},
            )
    elif settings.YOUTUBE_COOKIES_BROWSER:
        ydl_opts["cookiesfrombrowser"] = (settings.YOUTUBE_COOKIES_BROWSER,)
        logger.info(
            "Using browser cookies for YouTube download",
            extra={"browser": settings.YOUTUBE_COOKIES_BROWSER},
        )


BASE_FORMAT = "bestvideo[height<=720]+bestaudio/best"
FALLBACK_FORMATS = [
    "bestvideo+bestaudio/best",
    "best",
]


def _build_ydl_options(
    output_template: Path, max_file_size: int, *, format_string: str
) -> dict[str, object]:
    ydl_opts: dict[str, object] = {
        "format": format_string,
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
    _apply_cookie_auth(ydl_opts)
    return ydl_opts


def _attach_bearer_token(_ydl_opts: dict[str, object], _access_token: str | None) -> None:
    """
    NOTE: YouTube OAuth tokens cannot be used for video downloads with yt-dlp.

    YouTube Data API (OAuth) and YouTube video player (cookies) use separate auth systems.
    OAuth tokens are for API operations (upload, manage), not for downloading videos.

    yt-dlp requires browser session cookies for downloads. The OAuth connection in the
    admin UI is for future features like uploading clips, not for downloading source videos.

    This function is kept for documentation and potential future use with other platforms.
    """
    # OAuth bearer tokens don't work with yt-dlp for YouTube downloads
    pass


def _load_cookie_jar(path: Path) -> MozillaCookieJar | None:
    jar = MozillaCookieJar()
    try:
        jar.load(str(path), ignore_discard=True, ignore_expires=True)
        return jar
    except FileNotFoundError:
        logger.warning(
            "Transcript cookies file not found",
            extra={"cookies_file": str(path)},
        )
    except Exception as exc:  # pragma: no cover - depends on cookie contents
        logger.warning(
            "Failed to load transcript cookies",
            extra={"cookies_file": str(path), "error": str(exc)},
        )
    return None


def _build_transcript_http_client() -> Session | None:
    cookies_file = settings.YOUTUBE_COOKIES_FILE
    if not cookies_file:
        return None

    path = Path(cookies_file)
    jar = _load_cookie_jar(path)
    if jar is None:
        return None

    session = Session()
    session.cookies.update(jar)
    session.headers.setdefault("User-Agent", TRANSCRIPT_USER_AGENT)
    logger.info(
        "Using cookies file for YouTube transcript fetch",
        extra={"cookies_file": str(path)},
    )
    return session


def _build_transcript_api() -> YouTubeTranscriptApi:
    http_client = _build_transcript_http_client()
    return YouTubeTranscriptApi(http_client=http_client)


def _fetch_transcript_from_captions_api(
    video_id: str, access_token: str
) -> tuple[str | None, str | None]:
    headers = {"Authorization": f"Bearer {access_token}"}
    params: dict[str, str] = {"part": "snippet", "videoId": video_id, "maxResults": "50"}
    with httpx.Client(timeout=15) as client:
        response = client.get(CAPTIONS_API_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        items: list[dict[str, Any]] = data.get("items", [])
        if not items:
            return None, None

        caption = _pick_caption_track(items)
        if caption is None:
            logger.warning(
                "YouTube API returned no usable caption tracks",
                extra={"video_id": video_id, "tracks": len(items)},
            )
            return None, None

        caption_id = caption["id"]
        snippet = caption.get("snippet", {})
        logger.info(
            "Selected caption track",
            extra={
                "video_id": video_id,
                "caption_id": caption_id,
                "language": snippet.get("language"),
                "track_kind": snippet.get("trackKind"),
            },
        )
        download = client.get(
            f"{CAPTIONS_API_URL}/{caption_id}",
            headers=headers,
            params={"tfmt": "srt"},
        )
        download.raise_for_status()
        text = _parse_srt(download.text)
        language = snippet.get("language")
        return (text or None, language)


def _pick_caption_track(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    manual: list[tuple[str, dict[str, Any]]] = []
    generated: list[tuple[str, dict[str, Any]]] = []

    for item in items:
        snippet = item.get("snippet", {})
        lang = (snippet.get("language") or "").lower()
        track_kind = (snippet.get("trackKind") or "").lower()
        bucket = generated if track_kind == "asr" else manual
        bucket.append((lang, item))

    def _pick(bucket: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
        for preferred in PREFERRED_TRANSCRIPT_LANGS:
            for lang, entry in bucket:
                if lang == preferred or lang.startswith(f"{preferred}-"):
                    return entry
        return bucket[0][1] if bucket else None

    return _pick(manual) or _pick(generated)


def _parse_srt(payload: str) -> str:
    lines: list[str] = []
    for line in payload.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit() or "-->" in stripped:
            continue
        lines.append(stripped)
    return " ".join(lines).strip()


def _fetch_transcript_with_oauth(video_id: str, access_token: str) -> tuple[str | None, str | None]:
    try:
        logger.info(
            "Fetching transcript via YouTube Data API",
            extra={"video_id": video_id},
        )
        result = _fetch_transcript_from_captions_api(video_id, access_token)
        logger.info(
            "Transcript fetched via YouTube Data API",
            extra={"video_id": video_id, "has_text": bool(result[0])},
        )
        return result
    except httpx.HTTPStatusError as exc:
        body_preview = exc.response.text[:300]
        logger.warning(
            "YouTube API transcript request failed",
            extra={
                "video_id": video_id,
                "status_code": exc.response.status_code,
                "body": body_preview,
            },
        )
        if exc.response.status_code == CAPTIONS_FORBIDDEN_STATUS:
            logger.warning(
                "YouTube captions API returned 403. Ask the operator to reconnect their "
                "YouTube account so the new captions scope is granted.",
                extra={"video_id": video_id},
            )
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning(
            "Unexpected error fetching transcript via OAuth",
            extra={"video_id": video_id, "error": str(exc)},
        )
    return None, None


def _ensure_final_file(storage_dir: Path, final_output_path: Path) -> None:
    if final_output_path.exists():
        return
    for candidate in storage_dir.glob("source.*"):
        if candidate != final_output_path:
            candidate.rename(final_output_path)
            break


def _cleanup_partial_file(final_output_path: Path) -> None:
    if final_output_path.exists():
        final_output_path.unlink()


@dataclass(slots=True)
class _DownloadContext:
    video_id: int
    source_url: str
    storage_dir: Path
    output_template: Path
    final_output_path: Path
    max_file_size: int


def _log_available_formats(source_url: str) -> None:
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(source_url, download=False)
            formats = info.get("formats") or []
            preview = [
                {
                    "format_id": fmt.get("format_id"),
                    "ext": fmt.get("ext"),
                    "height": fmt.get("height"),
                    "width": fmt.get("width"),
                    "note": fmt.get("format_note"),
                }
                for fmt in formats[:10]
            ]
            logger.info(
                "Available YouTube formats",
                extra={
                    "source_url": source_url,
                    "total_formats": len(formats),
                    "sample": preview,
                },
            )
    except Exception as exc:  # pragma: no cover - network access
        logger.warning(
            "Failed to list YouTube formats",
            extra={"source_url": source_url, "error": str(exc)},
        )


def _execute_download(
    *,
    context: _DownloadContext,
    format_string: str,
) -> tuple[int, int]:
    ydl_opts = _build_ydl_options(
        context.output_template, context.max_file_size, format_string=format_string
    )
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(
                "Starting video download",
                extra={
                    "video_id": context.video_id,
                    "source_url": context.source_url,
                    "format": format_string,
                },
            )

            info: dict[str, Any] | None = ydl.extract_info(context.source_url, download=True)
            if not info:
                raise DownloadError("Failed to extract video information")

            duration = int(info.get("duration", 0))
            _ensure_final_file(context.storage_dir, context.final_output_path)

            if not context.final_output_path.exists():
                raise DownloadError(
                    f"Download completed but file not found at {context.final_output_path}"
                )

            file_size = context.final_output_path.stat().st_size
            if file_size > context.max_file_size:
                _cleanup_partial_file(context.final_output_path)
                raise VideoTooLargeError(
                    f"Video size ({file_size / 1024 / 1024:.1f} MB) "
                    f"exceeds limit ({settings.MAX_VIDEO_FILE_SIZE_MB} MB)"
                )

            logger.info(
                "Video downloaded successfully",
                extra={
                    "video_id": context.video_id,
                    "file_size_mb": file_size / 1024 / 1024,
                    "duration_seconds": duration,
                },
            )
            return file_size, duration

    except yt_dlp.utils.DownloadError as exc:
        error_msg = str(exc)
        logger.exception(
            "yt-dlp download failed",
            extra={
                "video_id": context.video_id,
                "source_url": context.source_url,
                "error": error_msg,
            },
        )
        _cleanup_partial_file(context.final_output_path)

        # Detect authentication errors (bot check, sign-in required)
        if "Sign in to confirm" in error_msg or "cookies" in error_msg.lower():
            raise AuthenticationRequiredError(
                f"Video download failed: {exc}. "
                "YouTube requires authentication. Export your browser cookies and upload to "
                "YOUTUBE_COOKIES_B64 secret. See docs/setup/youtube_cookies_setup.md"
            ) from exc

        if "Requested format is not available" in error_msg:
            _log_available_formats(context.source_url)
            raise FormatUnavailableError(error_msg) from exc

        raise DownloadError(f"Video download failed: {exc}") from exc
    except Exception as exc:
        logger.exception(
            "Unexpected error during download",
            extra={
                "video_id": context.video_id,
                "source_url": context.source_url,
                "error": str(exc),
            },
        )
        _cleanup_partial_file(context.final_output_path)
        raise DownloadError(f"Unexpected download error: {exc}") from exc


def _download_with_fallback_formats(context: _DownloadContext) -> tuple[int, int]:
    formats_to_try = [BASE_FORMAT, *FALLBACK_FORMATS]
    last_error: FormatUnavailableError | None = None

    for fmt in formats_to_try:
        try:
            return _execute_download(context=context, format_string=fmt)
        except FormatUnavailableError as exc:
            last_error = exc
            logger.warning(
                "Requested format unavailable; retrying with fallback",
                extra={"video_id": context.video_id, "format": fmt},
            )
            continue

    if last_error is not None:
        raise DownloadError(
            f"No compatible YouTube formats were available (tried {formats_to_try})"
        ) from last_error

    # Should not reach here, but raise generic error just in case.
    raise DownloadError("Video download failed before attempting any formats")


def _safe_transcript_lookup(
    source_url: str, *, access_token: str | None = None
) -> tuple[str | None, str | None]:
    try:
        yt_video_id = _extract_video_id(source_url)
        return _fetch_transcript(yt_video_id, access_token=access_token)
    except Exception as exc:
        logger.warning(
            "Failed to fetch transcript, continuing without it",
            extra={"source_url": source_url, "error": str(exc)},
        )
        return None, None


def download_video_and_transcript(
    video_id: int,
    source_url: str,
    *,
    access_token: str | None = None,
) -> DownloadResult:  # pragma: no cover - exercises external downloads
    """
    Download YouTube video and transcript.

    Args:
        video_id: Database video ID for organizing storage
        source_url: YouTube video URL
    """
    storage_dir, output_template, final_output_path = _prepare_storage_paths(video_id)
    max_file_size = settings.MAX_VIDEO_FILE_SIZE_MB * 1024 * 1024
    context = _DownloadContext(
        video_id=video_id,
        source_url=source_url,
        storage_dir=storage_dir,
        output_template=output_template,
        final_output_path=final_output_path,
        max_file_size=max_file_size,
    )
    file_size, duration = _download_with_fallback_formats(context)
    transcript, transcript_language = _safe_transcript_lookup(source_url, access_token=access_token)
    logger.info(
        "Transcript lookup complete",
        extra={
            "video_id": video_id,
            "has_transcript": bool(transcript),
            "access_token_used": bool(access_token),
        },
    )
    return DownloadResult(
        local_path=str(final_output_path),
        file_size_bytes=file_size,
        transcript_text=transcript,
        transcript_language=transcript_language,
        duration_seconds=duration,
    )
