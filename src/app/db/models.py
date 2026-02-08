from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)

# ... (skipping unchanged lines)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

__all__ = [
    "User",
    "UserOAuthAccount",
    "Video",
    "Clip",
    "PublishJob",
    "PublishJobStatus",
    "YouTubeCredential",
    "VideoStatus",
    "ClipStatus",
    "AuthProvider",
    "ClipGenerationMode",
    "VideoIngestType",
]


class VideoStatus(StrEnum):
    INGESTED = "ingested"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class ClipStatus(StrEnum):
    RENDERING = "rendering"
    READY = "ready"
    PUBLISHED_PARTIAL = "published_partial"
    PUBLISHED_ALL = "published_all"
    ERROR = "error"


class AuthProvider(StrEnum):
    EMAIL = "email"
    GOOGLE = "google"


class ClipGenerationMode(StrEnum):
    REPLACE = "replace"
    APPEND = "append"


class VideoIngestType(StrEnum):
    YOUTUBE = "youtube"
    UPLOAD = "upload"


class UserOAuthAccount(Base):
    __tablename__ = "user_oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        UniqueConstraint("user_id", "provider", name="uq_user_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    picture_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(
        "User",
        back_populates="oauth_accounts",
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_auth_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AuthProvider.EMAIL.value,
        server_default=AuthProvider.EMAIL.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    oauth_accounts: Mapped[list[UserOAuthAccount]] = relationship(
        "UserOAuthAccount",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    youtube_credential: Mapped[YouTubeCredential | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ingest_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=VideoIngestType.YOUTUBE.value,
        server_default=VideoIngestType.YOUTUBE.value,
    )
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    upload_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upload_file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    upload_original_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_root: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    render_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=VideoStatus.INGESTED.value,
        server_default=VideoStatus.INGESTED.value,
    )
    clip_generation_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ClipGenerationMode.REPLACE.value,
        server_default=ClipGenerationMode.REPLACE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    clips: Mapped[list[Clip]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
    )
    requested_by: Mapped[User | None] = relationship(foreign_keys=[requested_by_user_id])


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    end_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    asset_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    asset_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asset_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ready_local_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE"), default=False
    )
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ClipStatus.RENDERING.value,
        server_default=ClipStatus.RENDERING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    video: Mapped[Video] = relationship(back_populates="clips")


class PublishJobStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PUBLISHING = "publishing"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"


class PublishJob(Base):
    __tablename__ = "publish_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clip_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PublishJobStatus.PENDING.value,
        server_default=PublishJobStatus.PENDING.value,
    )
    asset_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    asset_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asset_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    response_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    clip: Mapped[Clip] = relationship("Clip")


class YouTubeCredential(Base):
    __tablename__ = "youtube_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    access_token: Mapped[str] = mapped_column(String(2048), nullable=False)
    refresh_token: Mapped[str] = mapped_column(String(2048), nullable=False)
    token_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="youtube_credential")
