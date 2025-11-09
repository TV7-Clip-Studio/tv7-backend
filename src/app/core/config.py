from __future__ import annotations

from typing import cast

from pydantic import AnyHttpUrl, AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")
    APP_NAME: str = "TV7"
    APP_ENV: str = "dev"
    DEBUG: bool = True
    VERSION: str = "0.1.0"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    TRUSTED_HOSTS: list[str] = ["*"]
    BACKEND_BASE_URL: AnyHttpUrl = cast(AnyHttpUrl, "http://localhost:8000")
    DATABASE_URL: AnyUrl = cast(
        AnyUrl, "postgresql+asyncpg://postgres:postgres@localhost:5432/appdb"
    )
    ADMIN_USERNAME: str | None = None
    ADMIN_PASSWORD: str | None = None
    REDIS_URL: str = "redis://localhost:6379/0"
    DRAMATIQ_BROKER: str = "stub"
    WORKER_CONCURRENCY: int = 4
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRES_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRES_MINUTES: int = 60 * 24 * 7  # one week
    MEDIA_STORAGE_DIR: str = "./media"
    VIDEO_QUALITY: str = "720p"
    MAX_VIDEO_FILE_SIZE_MB: int = 500
    OPENAI_API_KEY: str | None = None
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_PATH: str = "/api/v1/auth/google/callback"
    OAUTH_STATE_SECRET: str = "change-me-oauth-state"
    API_PORT: int = 8000
    UI_ADMIN_EMAIL: str | None = None
    UI_ADMIN_PASSWORD: str | None = None

    @property
    def ui_base_url(self) -> str:
        """Construct UI base URL from API_PORT for test fixtures."""
        return f"http://127.0.0.1:{self.API_PORT}"

    @property
    def google_redirect_uri(self) -> str:
        base = str(self.BACKEND_BASE_URL).rstrip("/")
        path = (
            self.GOOGLE_REDIRECT_PATH
            if self.GOOGLE_REDIRECT_PATH.startswith("/")
            else f"/{self.GOOGLE_REDIRECT_PATH}"
        )
        return f"{base}{path}"


settings = Settings()
