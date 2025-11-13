from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.db.models import Clip, Video
from app.services import clipper
from app.services.clipper import ClipRenderError, ClipRenderResult, render_clip
from app.services.render_workspace import VideoWorkspace, get_video_workspace


def _setup_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, video_id: int = 1
) -> VideoWorkspace:
    monkeypatch.setattr(clipper.settings, "MEDIA_STORAGE_DIR", str(tmp_path), raising=False)
    workspace = get_video_workspace(video_id)
    monkeypatch.setattr(clipper, "_probe_dimensions", lambda *_: (1920, 1080))
    return workspace


def test_render_clip_writes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _setup_workspace(tmp_path, monkeypatch)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-bytes")

    video = Video(id=1, source_url="https://youtube.com/watch?v=clip", local_path=str(source))
    video.duration_seconds = 120
    clip = Clip(id=10, video_id=1, start_sec=0, end_sec=30)

    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text
        if cmd[0] == clipper.settings.FFMPEG_BIN:
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"clip-bytes")
        else:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"streams":[{"width":1080,"height":1920,"r_frame_rate":"30/1"}]}',
                stderr="",
            )
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(clipper.subprocess, "run", fake_run)

    result = render_clip(video, clip, workspace)

    assert isinstance(result, ClipRenderResult)
    assert result.final_path.exists()
    assert result.width == 1080
    assert result.height == 1920
    assert result.frame_rate == pytest.approx(30.0)
    assert result.file_size_bytes > 0
    assert result.public_url.endswith("/10.mp4")
    assert any(cmd[0] == clipper.settings.FFMPEG_BIN for cmd in calls)


def test_render_clip_clamps_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _setup_workspace(tmp_path, monkeypatch)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    video = Video(id=7, source_url="https://youtube.com/watch?v=long", local_path=str(source))
    video.duration_seconds = 20
    clip = Clip(id=5, video_id=7, start_sec=0, end_sec=200)

    recorded_cmd: list[str] = []

    def fake_run(
        cmd: list[str], check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text
        if cmd[0] == clipper.settings.FFMPEG_BIN:
            recorded_cmd[:] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"data")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"streams":[{"width":720,"height":1280,"r_frame_rate":"24/1"}]}',
            stderr="",
        )

    monkeypatch.setattr(clipper.subprocess, "run", fake_run)
    render_clip(video, clip, workspace)
    assert "-to" in recorded_cmd
    to_index = recorded_cmd.index("-to")
    assert recorded_cmd[to_index + 1] == "20"  # clamped to video duration


def test_render_clip_reuses_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _setup_workspace(tmp_path, monkeypatch, video_id=2)
    final_path = workspace.clips_dir / "3.mp4"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(b"existing")

    source = tmp_path / "src.mp4"
    source.write_bytes(b"video")
    video = Video(id=2, source_url="https://youtube.com/watch?v=skip", local_path=str(source))
    video.duration_seconds = 40
    clip = Clip(id=3, video_id=2, start_sec=0, end_sec=20)

    run_calls = 0

    def fake_run(
        cmd: list[str], check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        nonlocal run_calls
        del check, capture_output, text
        if cmd[0] == clipper.settings.FFPROBE_BIN:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"streams":[{"width":720,"height":1280,"r_frame_rate":"60/1"}]}',
                stderr="",
            )
        run_calls += 1
        raise AssertionError("ffmpeg should not run when overwrite=False")

    monkeypatch.setattr(clipper.subprocess, "run", fake_run)
    result = render_clip(video, clip, workspace, overwrite=False)
    assert result.file_size_bytes == final_path.stat().st_size
    assert run_calls == 0


def test_render_clip_pads_tall_video(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _setup_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(clipper, "_probe_dimensions", lambda *_: (1080, 2340))
    source = tmp_path / "tall.mp4"
    source.write_bytes(b"bytes")
    video = Video(id=4, source_url="https://youtube.com/watch?v=tall", local_path=str(source))
    video.duration_seconds = 180
    clip = Clip(id=8, video_id=4, start_sec=10, end_sec=40)

    recorded_cmd: list[str] = []

    def fake_run(
        cmd: list[str], check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text
        if cmd[0] == clipper.settings.FFMPEG_BIN:
            recorded_cmd[:] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"clip")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"streams":[{"width":720,"height":1280,"r_frame_rate":"30/1"}]}',
            stderr="",
        )

    monkeypatch.setattr(clipper.subprocess, "run", fake_run)
    render_clip(video, clip, workspace)
    vf_index = recorded_cmd.index("-vf")
    vf_arg = recorded_cmd[vf_index + 1]
    assert "pad=" in vf_arg
    assert "crop=" not in vf_arg


def test_render_clip_raises_on_ffmpeg_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _setup_workspace(tmp_path, monkeypatch)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"bad")
    video = Video(id=9, source_url="https://youtube.com/watch?v=fail", local_path=str(source))
    clip = Clip(id=1, video_id=9, start_sec=5, end_sec=10)

    def fake_run(
        cmd: list[str], check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        del cmd, check, capture_output, text
        raise subprocess.CalledProcessError(returncode=1, cmd="ffmpeg", stderr="explode")

    monkeypatch.setattr(clipper.subprocess, "run", fake_run)
    with pytest.raises(ClipRenderError):
        render_clip(video, clip, workspace, overwrite=True)
