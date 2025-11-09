from __future__ import annotations

from typing import cast

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

HTTP_DEFAULT_PORT = 80
HTTPS_DEFAULT_PORT = 443


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")
    APP_NAME: str = "TV7"
    APP_ENV: str = "dev"
    DEBUG: bool = True
    VERSION: str = "0.1.0"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    TRUSTED_HOSTS: list[str] = ["*"]
    API_SCHEME: str = "http"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
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

    @property
    def google_redirect_uri(self) -> str:
        base = self.backend_base_url.rstrip("/")
        path = (
            self.GOOGLE_REDIRECT_PATH
            if self.GOOGLE_REDIRECT_PATH.startswith("/")
            else f"/{self.GOOGLE_REDIRECT_PATH}"
        )
        return f"{base}{path}"


settings = Settings()
