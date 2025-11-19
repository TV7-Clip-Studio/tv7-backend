from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.services import youtube_downloader


@dataclass
class _Snippet:
    text: str


@dataclass
class _DummyTranscript:
    language_code: str
    is_generated: bool
    lines: list[str]

    def fetch(self) -> list[_Snippet]:
        return [_Snippet(text=line) for line in self.lines]


class _DummyTranscriptList:
    def __init__(self, transcripts: list[_DummyTranscript]) -> None:
        self._transcripts = transcripts

    def __iter__(self) -> Iterator[_DummyTranscript]:
        return iter(self._transcripts)


def _set_transcripts(monkeypatch: pytest.MonkeyPatch, transcripts: list[_DummyTranscript]) -> None:
    class FakeAPI:
        def list(self, video_id: str) -> _DummyTranscriptList:  # noqa: ARG002
            return _DummyTranscriptList(transcripts)

    monkeypatch.setattr(youtube_downloader, "_build_transcript_api", lambda: FakeAPI())


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


def test_fetch_transcript_prefers_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        youtube_downloader,
        "_fetch_transcript_with_oauth",
        lambda video_id, token: (f"oauth-{video_id}-{token}", "en"),
    )

    def _should_not_run() -> None:
        raise AssertionError("Fallback API should not execute when OAuth succeeds")

    monkeypatch.setattr(youtube_downloader, "_build_transcript_api", _should_not_run)

    text, language = youtube_downloader._fetch_transcript("abc123", access_token="token")  # type: ignore[attr-defined]
    assert text == "oauth-abc123-token"
    assert language == "en"


def test_fetch_transcript_falls_back_when_oauth_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        youtube_downloader,
        "_fetch_transcript_with_oauth",
        lambda _video_id, _token: (None, None),
    )

    transcripts = [
        _DummyTranscript(language_code="en", is_generated=False, lines=["Hi"]),
    ]
    _set_transcripts(monkeypatch, transcripts)

    text, language = youtube_downloader._fetch_transcript("abc123", access_token="token")  # type: ignore[attr-defined]
    assert text == "Hi"
    assert language == "en"


def test_transcript_http_client_uses_cookie_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cookie_dir = tmp_path / "cookies"
    cookie_dir.mkdir()
    cookie_path = cookie_dir / "youtube_cookies.txt"
    cookie_path.write_text(
        "# Netscape HTTP Cookie File\n" ".youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\ttest-cookie\n"
    )

    monkeypatch.setattr(
        youtube_downloader.settings,
        "YOUTUBE_COOKIES_FILE",
        str(cookie_path),
        raising=False,
    )

    client = youtube_downloader._build_transcript_http_client()  # type: ignore[attr-defined]
    assert client is not None
    assert client.cookies.get("SAPISID") == "test-cookie"


def test_pick_caption_track_prefers_manual() -> None:
    items = [
        {
            "id": "auto",
            "snippet": {"language": "en", "trackKind": "ASR"},
        },
        {
            "id": "manual",
            "snippet": {"language": "en", "trackKind": "standard"},
        },
    ]
    selected = youtube_downloader._pick_caption_track(items)  # type: ignore[attr-defined]
    assert selected and selected["id"] == "manual"


def test_parse_srt_strips_metadata() -> None:
    payload = (
        """1\n00:00:00,000 --> 00:00:02,000\nHello\n\n2\n00:00:02,000 --> 00:00:04,000\nWorld\n"""
    )
    text = youtube_downloader._parse_srt(payload)  # type: ignore[attr-defined]
    assert text == "Hello World"


def test_fetch_transcript_from_captions_api(monkeypatch: pytest.MonkeyPatch) -> None:
    list_payload: dict[str, object] = {
        "items": [
            {
                "id": "caption-id",
                "snippet": {"language": "en", "trackKind": "standard"},
            }
        ]
    }
    caption_payload = (
        """1\n00:00:00,000 --> 00:00:02,000\nHello\n\n2\n00:00:02,000 --> 00:00:04,000\nWorld\n"""
    )

    class DummyResponse:
        def __init__(
            self, *, json_data: Mapping[str, object] | None = None, text: str = ""
        ) -> None:
            self._json = json_data
            self.text = text
            self.status_code = 200

        def raise_for_status(self) -> None:  # pragma: no cover - no failure path in test
            return None

        def json(self) -> dict[str, object]:
            return dict(self._json) if self._json is not None else {}

    class DummyClient:
        def __init__(self, *_: object, **__: object) -> None:
            self._calls = 0

        def __enter__(self) -> DummyClient:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, url: str, **_: object) -> DummyResponse:
            self._calls += 1
            if self._calls == 1:
                assert url.endswith("/captions")
                return DummyResponse(json_data=list_payload)
            assert "/captions/" in url
            return DummyResponse(text=caption_payload)

    monkeypatch.setattr(youtube_downloader.httpx, "Client", DummyClient)

    text, language = youtube_downloader._fetch_transcript_from_captions_api(  # type: ignore[attr-defined]
        "abc123",
        "token",
    )
    assert text == "Hello World"
    assert language == "en"


def _make_download_context(tmp_path: Path) -> youtube_downloader._DownloadContext:  # type: ignore[attr-defined]
    storage_dir = tmp_path / "videos" / "1"
    storage_dir.mkdir(parents=True)
    output_template = storage_dir / "source.%(ext)s"
    final_output = storage_dir / "source.mp4"
    return youtube_downloader._DownloadContext(  # type: ignore[attr-defined]
        video_id=1,
        source_url="https://example.com",
        storage_dir=storage_dir,
        output_template=output_template,
        final_output_path=final_output,
        max_file_size=10_000,
    )


def test_download_with_fallback_retries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    context = _make_download_context(tmp_path)
    calls: list[str] = []

    def fake_execute(*, format_string: str, **__: object) -> tuple[int, int]:
        calls.append(format_string)
        if format_string == youtube_downloader.BASE_FORMAT:
            raise youtube_downloader.FormatUnavailableError("missing")  # type: ignore[attr-defined]
        context.final_output_path.write_bytes(b"data")
        return 123, 10

    monkeypatch.setattr(youtube_downloader, "_execute_download", fake_execute)
    size, duration = youtube_downloader._download_with_fallback_formats(context)  # type: ignore[attr-defined]
    assert size == 123
    assert duration == 10
    assert calls[:2] == [
        youtube_downloader.BASE_FORMAT,
        youtube_downloader.FALLBACK_FORMATS[0],
    ]


def test_download_with_fallback_raises_after_exhaustion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = _make_download_context(tmp_path)

    def always_fail(*_: object, **__: object) -> tuple[int, int]:
        raise youtube_downloader.FormatUnavailableError("missing")  # type: ignore[attr-defined]

    monkeypatch.setattr(youtube_downloader, "_execute_download", always_fail)

    with pytest.raises(youtube_downloader.DownloadError):  # type: ignore[attr-defined]
        youtube_downloader._download_with_fallback_formats(context)  # type: ignore[attr-defined]
