from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import anyio
from faster_whisper import WhisperModel
from faster_whisper.transcribe import Segment, TranscriptionInfo

from app.core.config import settings


class TranscriptionError(Exception):
    """Raised when we cannot produce a transcript for a video."""


@dataclass(slots=True)
class TranscriptResult:
    text: str
    language_code: str | None


_MODEL: WhisperModel | None = None
_MODEL_LOCK = threading.Lock()


def _load_model() -> WhisperModel:
    global _MODEL  # noqa: PLW0603
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            _MODEL = WhisperModel(
                settings.WHISPER_MODEL_NAME,
                device=settings.WHISPER_DEVICE,
                compute_type=settings.WHISPER_COMPUTE_TYPE,
            )
    return _MODEL


def _transcribe_sync(local_path: str) -> TranscriptResult:
    file_path = Path(local_path)
    if not file_path.exists():
        raise TranscriptionError("Video file missing for transcription")

    model = _load_model()
    language_override = settings.WHISPER_LANGUAGE or None

    try:
        segments_iter, info = model.transcribe(
            str(file_path),
            beam_size=5,
            vad_filter=True,
            language=language_override,
        )
    except Exception as exc:  # pragma: no cover - heavy runtime errors
        raise TranscriptionError(f"Failed to transcribe upload: {exc}") from exc

    segments: list[Segment] = list(segments_iter)
    text_parts: list[str] = []
    for segment in segments:
        if segment.text:
            cleaned = segment.text.strip()
            if cleaned:
                text_parts.append(cleaned)

    if not text_parts:
        raise TranscriptionError("Transcription result was empty")

    language = language_override or getattr(cast(TranscriptionInfo, info), "language", None)
    return TranscriptResult(text=" ".join(text_parts), language_code=language)


async def transcribe_video_file(local_path: str) -> TranscriptResult:
    """Transcribe a video using the local faster-whisper model."""

    result = await anyio.to_thread.run_sync(_transcribe_sync, local_path)
    return cast(TranscriptResult, result)
