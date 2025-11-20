from __future__ import annotations

from pathlib import Path

import pytest

from app.services import transcription


class _DummySegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _DummyInfo:
    language = "es"


class _DummyModel:
    def transcribe(self, *_: object, **__: object) -> tuple[list[_DummySegment], _DummyInfo]:
        return ([_DummySegment("hola"), _DummySegment(" mundo")], _DummyInfo())


def test_transcribe_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"0")

    monkeypatch.setattr(transcription, "_load_model", lambda: _DummyModel())

    result = transcription._transcribe_sync(str(media))

    assert result.text == "hola mundo"
    assert result.language_code == "es"


@pytest.mark.anyio
async def test_transcribe_video_file(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = transcription.TranscriptResult(text="ok", language_code="en")

    async def fake_run(
        _func: object, *_args: object, **_kwargs: object
    ) -> transcription.TranscriptResult:
        return expected

    monkeypatch.setattr(transcription.anyio.to_thread, "run_sync", fake_run)

    result = await transcription.transcribe_video_file("does-not-matter")

    assert result == expected
