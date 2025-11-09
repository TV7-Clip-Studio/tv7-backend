from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.jwt import TokenType
from app.db.models import ClipStatus, VideoStatus


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
    caption_text: str | None
    status: ClipStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VideoRead(BaseModel):
    id: int
    source_url: str
    local_path: str | None
    transcript_text: str | None
    transcript_language: str | None = None
    duration_seconds: int | None = None
    file_size_bytes: int | None = None
    error_message: str | None = None
    status: VideoStatus
    created_at: datetime
    updated_at: datetime
    requested_by_user_id: int | None = None
    clips: list[ClipRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
