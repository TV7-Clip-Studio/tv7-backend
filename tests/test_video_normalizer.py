from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services import video_normalizer


def test_normalize_uploaded_video(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mov"
    source.write_bytes(b"raw-video")

    def fake_storage(video_id: int) -> Path:  # noqa: ARG001
        target = tmp_path / "videos" / "storage"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def fake_run(cmd: list[str], **_: Any) -> None:
        Path(cmd[-1]).write_bytes(b"normalized")

    monkeypatch.setattr(video_normalizer, "ensure_video_storage", fake_storage)
    monkeypatch.setattr(video_normalizer.subprocess, "run", fake_run)
    monkeypatch.setattr(video_normalizer, "_ffprobe_duration_seconds", lambda _: 42)

    result = video_normalizer.normalize_uploaded_video(1, source)

    assert Path(result.normalized_path).exists()
    assert result.duration_seconds == 42
    assert not source.exists()
