from __future__ import annotations

from pathlib import Path

import pytest

from app.services import render_workspace
from app.services.render_workspace import get_video_workspace


def test_video_workspace_creates_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        render_workspace.settings, "MEDIA_STORAGE_DIR", str(tmp_path), raising=False
    )

    workspace = get_video_workspace(42)

    assert workspace.source_dir.exists()
    assert workspace.clips_dir.exists()
    assert workspace.temp_dir.exists()

    clip_paths = workspace.clip_paths(clip_id=7)
    assert clip_paths.final_path == workspace.clips_dir / "7.mp4"
    assert clip_paths.public_url == "/media/clips/42/7.mp4"
    assert clip_paths.temp_dir.exists()
    assert clip_paths.temp_dir == workspace.temp_dir / "7"
    assert clip_paths.mezzanine_video.parent == clip_paths.temp_dir / "mezzanine"
    assert clip_paths.subtitles_file.parent == clip_paths.temp_dir / "subtitles"

    workspace.cleanup_clip(clip_id=7)
    assert not clip_paths.temp_dir.exists()
