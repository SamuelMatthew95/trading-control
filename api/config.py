"""
Production settings configuration using Pydantic
Provides robust validation and environment variable management
"""

import os
from typing import Optional

from pydantic import (BaseSettings, PostgresDsn, ValidationError,
                      field_validator)
from pydantic_settings import BaseSettings as PydanticBaseSettings


class Settings(PydanticBaseSettings):
    """Production settings with Pydantic validation"""

    # Database configuration with automatic validation
    DATABASE_URL: PostgresDsn = Field(
        default=None, description="PostgreSQL connection string for persistent storage"
    )

    # API Keys
    ANTHROPIC_API_KEY: str = Field(
        default=None, description="Claude API key for AI agents"
    )

    # Application settings
    NODE_ENV: str = Field(default="development", description="Application environment")

    NEXT_PUBLIC_APP_URL: str = Field(
        default="http://localhost:3000", description="Frontend application URL"
    )

    # Optional observability
    LANGFUSE_PUBLIC_KEY: Optional[str] = Field(
        default=None, description="Langfuse public key for observability"
    )

    LANGFUSE_SECRET_KEY: Optional[str] = Field(
        default=None, description="Langfuse secret key for observability"
    )

    NEXT_PUBLIC_VERCEL_ANALYTICS_ID: Optional[str] = Field(
        default=None, description="Vercel Analytics ID"
    )

    NEXT_PUBLIC_VERCEL_SPEED_INSIGHTS_ID: Optional[str] = Field(
        default=None, description="Vercel Speed Insights ID"
    )

    # Performance settings
    API_TIMEOUT: int = Field(
        default=30000, description="API request timeout in milliseconds"
    )

    MAX_RETRIES: int = Field(default=3, description="Maximum API retry attempts")

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def ensure_async_driver(cls, v: Optional[PostgresDsn]) -> Optional[str]:
        """Transform postgresql:// to postgresql+asyncpg:// for SQLAlchemy async"""
        if v is None:
            return None

        url_str = str(v)
        # Ensure URL has async driver for SQLAlchemy
        if url_str.startswith("postgresql://") or url_str.startswith("postgres://"):
            return url_str.replace("://", "+asyncpg://", 1)
        return url_str

    @field_validator("ANTHROPIC_API_KEY")
    @classmethod
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Validate API key is present and not empty"""
        if v is not None and len(v.strip()) == 0:
            raise ValueError("ANTHROPIC_API_KEY cannot be empty")
        return v

    @field_validator("NODE_ENV")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment is one of allowed values"""
        allowed_envs = ["development", "staging", "production"]
        if v not in allowed_envs:
            raise ValueError(f"NODE_ENV must be one of: {allowed_envs}")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # Allow extra fields without validation


# Create global settings instance
settings = Settings()

# Database URL for async SQLAlchemy
ASYNC_DATABASE_URL = settings.ensure_async_driver(settings.DATABASE_URL)


def get_database_url() -> str:
    """Get the properly formatted database URL for async SQLAlchemy"""
    if ASYNC_DATABASE_URL is None:
        raise ValueError("DATABASE_URL is required for database connection")
    return ASYNC_DATABASE_URL


def validate_all_settings() -> bool:
    """Validate all required settings are present"""
    try:
        # This will raise ValidationError if any required field is missing or invalid
        settings = Settings()
        print("✅ All settings validated successfully")
        return True
    except ValidationError as e:
        print("❌ Settings validation failed:")
        for error in e.errors():
            print(f"  ❌ {error['loc']}: {error['msg']}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error during validation: {e}")
        return False


if __name__ == "__main__":
    # Test settings validation
    if validate_all_settings():
        print("🎯 Configuration is production-ready!")
        print(f"Database URL: {ASYNC_DATABASE_URL}")
    else:
        print("🚨 Fix configuration before starting application!")
