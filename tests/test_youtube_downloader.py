from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from app.services import youtube_downloader


@dataclass
class _DummyTranscript:
    language_code: str
    is_generated: bool
    lines: list[str]

    def fetch(self) -> list[dict[str, str]]:
        return [{"text": line} for line in self.lines]


class _DummyTranscriptList:
    def __init__(self, transcripts: list[_DummyTranscript]) -> None:
        self._transcripts = transcripts

    def __iter__(self) -> Iterator[_DummyTranscript]:
        return iter(self._transcripts)


def _set_transcripts(monkeypatch: pytest.MonkeyPatch, transcripts: list[_DummyTranscript]) -> None:
    class FakeAPI:
        def list(self, video_id: str) -> _DummyTranscriptList:  # noqa: ARG002
            return _DummyTranscriptList(transcripts)

    monkeypatch.setattr(youtube_downloader, "YouTubeTranscriptApi", lambda: FakeAPI())


def test_fetch_transcript_prefers_manual_preferred_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcripts = [
        _DummyTranscript(language_code="es", is_generated=False, lines=["Hola", "Mundo"]),
        _DummyTranscript(language_code="en", is_generated=False, lines=["Hello", "World"]),
    ]
    _set_transcripts(monkeypatch, transcripts)

    text, language = youtube_downloader._fetch_transcript("abc123")  # type: ignore[attr-defined]
    assert text == "Hello World"
    assert language == "en"


def test_fetch_transcript_falls_back_to_generated(monkeypatch: pytest.MonkeyPatch) -> None:
    transcripts = [
        _DummyTranscript(language_code="es", is_generated=True, lines=["Linea", "uno"]),
    ]
    _set_transcripts(monkeypatch, transcripts)

    text, language = youtube_downloader._fetch_transcript("abc123")  # type: ignore[attr-defined]
    assert text == "Linea uno"
    assert language == "es"


def test_fetch_transcript_handles_non_preferred_language(monkeypatch: pytest.MonkeyPatch) -> None:
    transcripts = [
        _DummyTranscript(language_code="ru", is_generated=False, lines=["Привет", "мир"]),
    ]
    _set_transcripts(monkeypatch, transcripts)

    text, language = youtube_downloader._fetch_transcript("abc123")  # type: ignore[attr-defined]
    assert text == "Привет мир"
    assert language == "ru"
