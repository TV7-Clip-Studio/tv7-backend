from __future__ import annotations

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")
    APP_NAME: str = "My FastAPI Service"
    APP_ENV: str = "dev"
    DEBUG: bool = True
    VERSION: str = "0.1.0"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    TRUSTED_HOSTS: list[str] = ["*"]
    DATABASE_URL: AnyUrl = "postgresql+asyncpg://postgres:postgres@localhost:5432/appdb"


settings = Settings()
