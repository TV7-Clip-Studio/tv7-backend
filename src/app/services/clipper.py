from __future__ import annotations

import json
import logging
import subprocess  # nosec B404
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.models import Clip, Video
from app.services.render_workspace import VideoWorkspace

logger = logging.getLogger(__name__)


class ClipRenderError(Exception):
    """Raised when ffmpeg fails or inputs are invalid."""


@dataclass(slots=True)
class ClipRenderConfig:
    ffmpeg_bin: str = settings.FFMPEG_BIN
    ffprobe_bin: str = settings.FFPROBE_BIN
    max_duration_seconds: int = settings.CLIP_MAX_DURATION_SECONDS
    target_height: int = settings.CLIP_TARGET_HEIGHT
    output_bitrate: str = settings.CLIP_OUTPUT_BITRATE


@dataclass(slots=True)
class ClipRenderResult:
    final_path: Path
    public_url: str
    width: int | None
    height: int | None
    frame_rate: float | None
    file_size_bytes: int


def _parse_frame_rate(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            return float(Fraction(value))
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def _probe_metadata(
    path: Path, config: ClipRenderConfig
) -> tuple[int | None, int | None, float | None]:
    if not path.exists():
        return None, None, None
    cmd = [
        config.ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )  # nosec B603
    except FileNotFoundError as exc:  # pragma: no cover
        raise ClipRenderError(f"ffprobe not found: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "Failed to probe rendered clip",
            extra={"path": str(path), "stderr": exc.stderr},
        )
        return None, None, None

    try:
        data: dict[str, Any] = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None, None, None

    streams = data.get("streams") or []
    if not streams:
        return None, None, None
    stream = streams[0]
    width = stream.get("width")
    height = stream.get("height")
    frame_rate = _parse_frame_rate(stream.get("r_frame_rate"))
    return width, height, frame_rate


def _run_ffmpeg(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )  # nosec B603
    except FileNotFoundError as exc:  # pragma: no cover
        raise ClipRenderError(f"ffmpeg not found: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "unknown error"
        raise ClipRenderError(stderr) from exc


def _build_video_filter(target_height: int) -> str:
    # Scale height to target while maintaining aspect, then crop to 9:16.
    return f"scale=-2:{target_height},crop=ih*9/16:ih"


def render_clip(
    video: Video,
    clip: Clip,
    workspace: VideoWorkspace,
    *,
    overwrite: bool = False,
    config: ClipRenderConfig | None = None,
) -> ClipRenderResult:
    cfg = config or ClipRenderConfig()

    if not video.local_path:
        raise ClipRenderError("Video missing local_path for rendering")

    source_path = Path(video.local_path)
    if not source_path.exists():
        raise ClipRenderError(f"Source file missing at {source_path}")

    clip_paths = workspace.clip_paths(clip.id)
    clip_paths.final_path.parent.mkdir(parents=True, exist_ok=True)

    if clip_paths.final_path.exists() and not overwrite:
        width, height, frame_rate = _probe_metadata(clip_paths.final_path, cfg)
        clip_paths.cleanup()
        return ClipRenderResult(
            final_path=clip_paths.final_path,
            public_url=clip_paths.public_url,
            width=width,
            height=height,
            frame_rate=frame_rate,
            file_size_bytes=clip_paths.final_path.stat().st_size,
        )

    for candidate in (clip_paths.final_path, clip_paths.mezzanine_video):
        if candidate.exists():
            candidate.unlink()

    start_sec = max(0, int(clip.start_sec))
    end_sec = int(clip.end_sec)
    if video.duration_seconds:
        end_sec = min(end_sec, int(video.duration_seconds))
    if cfg.max_duration_seconds:
        end_sec = min(end_sec, start_sec + cfg.max_duration_seconds)
    if end_sec <= start_sec:
        raise ClipRenderError("Invalid clip duration after clamping bounds")

    cmd = [
        cfg.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(start_sec),
        "-to",
        str(end_sec),
        "-i",
        str(source_path),
        "-vf",
        _build_video_filter(cfg.target_height),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-profile:v",
        "high",
        "-b:v",
        cfg.output_bitrate,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(clip_paths.mezzanine_video),
    ]

    logger.info(
        "Rendering clip",
        extra={
            "video_id": video.id,
            "clip_id": clip.id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "ffmpeg_cmd": " ".join(cmd[:-1] + ["<output>"]),
        },
    )

    try:
        _run_ffmpeg(cmd)

        if not clip_paths.mezzanine_video.exists():
            raise ClipRenderError("ffmpeg did not produce output")

        clip_paths.final_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
        clip_paths.mezzanine_video.replace(clip_paths.final_path)

        width, height, frame_rate = _probe_metadata(clip_paths.final_path, cfg)

        return ClipRenderResult(
            final_path=clip_paths.final_path,
            public_url=clip_paths.public_url,
            width=width,
            height=height,
            frame_rate=frame_rate,
            file_size_bytes=clip_paths.final_path.stat().st_size,
        )
    finally:
        clip_paths.cleanup()
