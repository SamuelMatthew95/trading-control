"""Application settings with strict validation for production runtime."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, PostgresDsn, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: Optional[PostgresDsn] = Field(default=None)
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None)
    API_SECRET_KEY: Optional[str] = Field(default=None)

    NODE_ENV: Literal["development", "staging", "production"] = "development"
    NEXT_PUBLIC_APP_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: str = "http://localhost:3000,https://*.vercel.app,https://*.onrender.com"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1,*.vercel.app,*.onrender.com"

    API_TIMEOUT_MS: int = 30000
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_MS: int = 250
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> "Settings":
        if self.NODE_ENV == "production":
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL is required in production")
        return self


settings = Settings()


def get_database_url() -> str:
    if settings.DATABASE_URL is None:
        raise ValueError("DATABASE_URL is required for database connection")
    url = str(settings.DATABASE_URL)
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return url.replace("://", "+asyncpg://", 1)
    return url


def parse_csv_env(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def validate_all_settings() -> bool:
    try:
        Settings()
        return True
    except ValidationError:
        return False
