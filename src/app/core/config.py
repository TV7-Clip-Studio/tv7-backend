from __future__ import annotations

from typing import Any, cast

from pydantic import AnyUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

HTTP_DEFAULT_PORT = 80
HTTPS_DEFAULT_PORT = 443


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")
    APP_NAME: str = "TV7"
    APP_ENV: str = "dev"
    DEBUG: bool = True
    VERSION: str = "0.1.0"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "http://tauri.localhost",
    ]
    TRUSTED_HOSTS: list[str] = ["*"]
    API_SCHEME: str = "http"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    DATABASE_URL: AnyUrl = cast(
        AnyUrl, "postgresql+asyncpg://postgres:postgres@localhost:5432/appdb"
    )
    ADMIN_USERNAME: str | None = None
    ADMIN_PASSWORD: str | None = None
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRES_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRES_MINUTES: int = 60 * 24 * 7  # one week
    ENGINE_CLOUD_AI_TOKEN_EXPIRES_MINUTES: int = 15
    CLOUD_AI_DEFAULT_REQUEST_CREDITS: int = 1
    CLOUD_AI_CONTEXT_MAX_CHARS: int = 120_000
    CLOUD_AI_PROVIDER: str = "deepseek"
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_API_URL: str = "https://api.deepseek.com/chat/completions"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    ADMIN_CLOUD_AI_INITIAL_CREDITS: int = 1_000_000_000
    SOURCE_MEDIA_STORAGE_DIR: str = "./private_media/videos"
    SCHEDULED_ASSET_STORAGE_DIR: str = "./private_media/assets"
    ASSET_STORAGE_BACKEND: str = "local"
    ASSET_S3_BUCKET: str | None = None
    ASSET_S3_REGION: str | None = None
    ASSET_S3_ENDPOINT_URL: str | None = None
    ASSET_S3_ACCESS_KEY_ID: str | None = None
    ASSET_S3_SECRET_ACCESS_KEY: str | None = None
    ASSET_S3_SESSION_TOKEN: str | None = None
    ASSET_S3_PREFIX: str = "tv7/approved-assets"
    YOUTUBE_CLIENT_ID: str | None = None
    YOUTUBE_CLIENT_SECRET: str | None = None
    YOUTUBE_REDIRECT_URI: str | None = None
    YOUTUBE_TOKEN_ENCRYPTION_KEYS: str | None = None
    YOUTUBE_PUBLISH_ENABLED: bool = False
    YOUTUBE_API_AUDIT_APPROVED: bool = False
    UPLOAD_MAX_FILE_SIZE_MB: int = 4096
    LOG_OUTPUT_MODE: str = "medium"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if normalized in {"release", "prod", "production"}:
            return False
        if normalized in {"debug", "dev", "development"}:
            return True
        return value

    @property
    def backend_base_url(self) -> str:
        """Return the externally reachable base URL for this API."""
        scheme = (self.API_SCHEME or "http").strip(":/").lower() or "http"
        host = self.API_HOST.strip()
        if not host:
            host = "127.0.0.1"
        needs_port = not (
            (scheme == "http" and self.API_PORT == HTTP_DEFAULT_PORT)
            or (scheme == "https" and self.API_PORT == HTTPS_DEFAULT_PORT)
        )
        port_segment = f":{self.API_PORT}" if needs_port else ""
        return f"{scheme}://{host}{port_segment}"

    @property
    def ui_base_url(self) -> str:
        """Construct UI base URL from API_PORT for test fixtures."""
        return self.backend_base_url.rstrip("/")


settings = Settings()
