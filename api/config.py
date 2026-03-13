"""Application settings with validation for API and agent runtime."""

from __future__ import annotations

from typing import Literal, Optional, List

from pydantic import Field, PostgresDsn, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: Optional[PostgresDsn] = Field(default=None)
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None)
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    API_KEY: Optional[str] = None
    API_SECRET_KEY: Optional[str] = None

    NODE_ENV: Literal["development", "staging", "production"] = "development"
    NEXT_PUBLIC_APP_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"

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

    @field_validator("ANTHROPIC_API_KEY")
    @classmethod
    def validate_api_key(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("ANTHROPIC_API_KEY cannot be empty")
        return value


settings = Settings()


def get_database_url() -> str:
    if settings.DATABASE_URL is None:
        raise ValueError("DATABASE_URL is required for database connection")
    url = str(settings.DATABASE_URL)
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return url.replace("://", "+asyncpg://", 1)
    return url


def validate_all_settings() -> bool:
    try:
        Settings()
        return True
    except ValidationError:
        return False


def parse_csv_env(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def get_api_timeout_ms() -> int:
    """Backward-compatible timeout accessor in milliseconds."""
    return settings.API_TIMEOUT_MS
