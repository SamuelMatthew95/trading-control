"""Application settings with validation for API and agent runtime."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, PostgresDsn, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: Optional[PostgresDsn] = Field(default=None)
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None)
    NODE_ENV: Literal["development", "staging", "production"] = "development"
    NEXT_PUBLIC_APP_URL: str = "http://localhost:3000"
    API_TIMEOUT: int = 30000
    MAX_RETRIES: int = 3

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
