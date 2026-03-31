"""Application settings with strict validation for production runtime."""

from __future__ import annotations

from pydantic import (
    Field,
    PostgresDsn,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: PostgresDsn | None = Field(default=None)
    REDIS_URL: str | None = Field(default=None)
    ANTHROPIC_API_KEY: str | None = Field(default=None)
    ANTHROPIC_DAILY_TOKEN_BUDGET: int = 5_000_000
    LLM_FALLBACK_MODE: str = "skip_reasoning"
    BROKER_MODE: str = "paper"
    LLM_TIMEOUT_SECONDS: int = 15
    LLM_MAX_RETRIES: int = 2
    REFLECTION_TRADE_THRESHOLD: int = 20
    MAX_CONSUMER_LAG_ALERT: int = 5_000
    ANTHROPIC_COST_ALERT_USD: float = 5.0
    FRONTEND_URL: str = "http://localhost:3000"

    # Market data
    MARKET_DATA_PROVIDER: str = "alpaca"
    MARKET_TICK_INTERVAL_SECONDS: float = 10.0

    # Agent trigger thresholds
    SIGNAL_EVERY_N_TICKS: int = 10
    GRADE_EVERY_N_FILLS: int = 5
    IC_UPDATE_EVERY_N_FILLS: int = 10
    REFLECT_EVERY_N_FILLS: int = 10

    # LLM provider routing
    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Alpaca - use paper trading keys from alpaca.markets
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_PAPER: bool = True  # True = paper trading, False = live real money
    # Paper base URL: https://paper-api.alpaca.markets
    # Live base URL: https://api.alpaca.markets
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
    ALPACA_WS_URL: str = "wss://stream.data.alpaca.markets/v2/iex"

    # Optional - kept for backwards compatibility
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    OPENAI_API_KEY: str | None = Field(default=None)
    OPENAI_MODEL: str = "gpt-4o-mini"

    API_SECRET_KEY: str | None = Field(default=None)
    NODE_ENV: str = "development"
    NEXT_PUBLIC_APP_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: str = "http://localhost:3000,https://*.vercel.app,https://*.onrender.com"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1,*.vercel.app,*.onrender.com"
    API_TIMEOUT_MS: int = 30000
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_MS: int = 250
    LOG_LEVEL: str = "INFO"

    # Database connection pool (tune for Render PostgreSQL limits)
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # Redis connection pool (tune for Render Redis plan limits)
    REDIS_MAX_CONNECTIONS: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("FRONTEND_URL")
    @classmethod
    def normalize_frontend_url(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> Settings:
        if self.NODE_ENV == "production" and not self.DATABASE_URL:
            raise ValueError("DATABASE_URL is required in production")
        return self


settings = Settings()


def get_database_url() -> str:
    if settings.DATABASE_URL is None:
        return "sqlite+aiosqlite:///./trading-control.db"

    url = str(settings.DATABASE_URL)
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return url.replace("://", "+asyncpg://", 1)
    return url


def parse_csv_env(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def get_cors_origins() -> list[str]:
    origins = parse_csv_env(settings.ALLOWED_ORIGINS)
    if settings.FRONTEND_URL not in origins:
        origins.append(settings.FRONTEND_URL)
    return origins


def validate_all_settings() -> bool:
    try:
        Settings()
        return True
    except ValidationError:
        return False
