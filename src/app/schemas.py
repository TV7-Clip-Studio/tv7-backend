from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.jwt import TokenType
from app.db.models import (
    ClipGenerationMode,
    ClipStatus,
    PublishJobStatus,
    VideoIngestType,
    VideoStatus,
)


class Health(BaseModel):
    status: str = "ok"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str


class UserRead(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: EmailStr
    type: TokenType
    exp: int
    iat: int


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class ClipRead(BaseModel):
    id: int
    video_id: int
    start_sec: int
    end_sec: int
    local_path: str | None
    asset_url: str | None = None
    asset_checksum: str | None = None
    asset_size_bytes: int | None = None
    ready_local_only: bool = False
    caption_text: str | None
    render_width: int | None = None
    render_height: int | None = None
    frame_rate: float | None = None
    file_size_bytes: int | None = None
    thumbnail_path: str | None = None
    status: ClipStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VideoRead(BaseModel):
    id: int
    source_url: str
    local_path: str | None
    ingest_type: VideoIngestType
    original_filename: str | None = None
    upload_checksum: str | None = None
    upload_file_size_bytes: int | None = None
    transcript_text: str | None
    transcript_language: str | None = None
    duration_seconds: int | None = None
    file_size_bytes: int | None = None
    error_message: str | None = None
    workspace_root: str | None = None
    status: VideoStatus
    clip_generation_mode: ClipGenerationMode
    created_at: datetime
    updated_at: datetime
    requested_by_user_id: int | None = None
    clips: list[ClipRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PublishJobRead(BaseModel):
    id: int
    clip_id: int
    platform: str
    status: PublishJobStatus
    asset_url: str | None = None
    asset_checksum: str | None = None
    asset_size_bytes: int | None = None
    response_payload: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublishRequest(BaseModel):
    platforms: list[str]
    asset_url: str | None = None
    asset_checksum: str | None = None
    asset_size_bytes: int | None = None


class ConfigRead(BaseModel):
    publishing_enabled: bool
    asset_upload_required: bool
    allowed_platforms: list[str]
    max_asset_size_bytes: int | None = None
    max_video_duration_seconds: int | None = None
    publish_modes: list[Literal["backend_publish", "local_only"]] = Field(default_factory=list)


class AssetUploadResponse(BaseModel):
    asset_url: str
    asset_checksum: str
    asset_size_bytes: int
    content_type: str | None = None
