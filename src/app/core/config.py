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
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRES_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRES_MINUTES: int = 60 * 24 * 7  # one week
    MEDIA_STORAGE_DIR: str = "./media"
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
