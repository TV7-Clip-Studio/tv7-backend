from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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


class LicenseReadinessResponse(BaseModel):
    account_active: bool = Field(description="Whether the authenticated TV7 account is active.")
    license_status: Literal["active", "required"] = Field(
        description="Account-level cloud AI entitlement readiness."
    )
    cloud_ai_available: bool = Field(
        description="Whether TV7 cloud AI is currently available to this account."
    )
    cloud_ai_credits_remaining: int = Field(
        ge=0,
        description="Perpetual cloud AI credits remaining; purchased credits do not expire.",
    )
    can_request_engine_cloud_ai_token: bool = Field(
        description="Whether Studio may request a short-lived delegated Engine token."
    )
    engine_cloud_ai_scope: str = Field(
        default="engine:cloud_ai",
        description="Required scope for delegated Engine cloud AI execution.",
    )
    reason_code: Literal["READY", "AI_LICENSE_REQUIRED", "AI_QUOTA_EXCEEDED"] = Field(
        description="Stable readiness reason for Studio diagnostics and account UX."
    )


class EngineCloudAiTokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    scope: str = "engine:cloud_ai"
    expires_in_seconds: int
    credits_remaining: int


class CloudAiMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class CloudAiExecuteRequest(BaseModel):
    messages: list[CloudAiMessage] = Field(min_length=1)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0, le=8192)


class CloudAiUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    credits_charged: int
    credits_remaining: int
    latency_ms: int | None = None


class CloudAiExecuteResponse(BaseModel):
    provider: str
    model: str
    content: str
    usage: CloudAiUsage
    raw_finish_reason: str | None = None


class CloudAiErrorResponse(BaseModel):
    code: Literal[
        "AI_AUTH_REQUIRED",
        "AI_LICENSE_REQUIRED",
        "AI_QUOTA_EXCEEDED",
        "AI_PROVIDER_UNAVAILABLE",
        "AI_NETWORK_UNAVAILABLE",
        "AI_CONTEXT_TOO_LARGE",
    ]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


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
