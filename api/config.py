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
    # When True, skip all PostgreSQL connection attempts and run with Redis +
    # InMemoryStore as the persistence layer. Production-friendly switch so we
    # do not noise DNS-failure warnings every health check.
    USE_MEMORY_MODE: bool = Field(default=False)
    ANTHROPIC_API_KEY: str | None = Field(default=None)
    ANTHROPIC_DAILY_TOKEN_BUDGET: int = 5_000_000
    LLM_FALLBACK_MODE: str = "skip_reasoning"
    ALLOW_FALLBACK_TRADES: bool = False
    MAX_FALLBACK_ORDER_QTY: float = 0.01
    MAX_SYMBOL_EXPOSURE: float = 1.0
    MAX_OPEN_POSITION_QTY: float = 1.0
    BROKER_MODE: str = "paper"
    LLM_TIMEOUT_SECONDS: int = 90
    LLM_MAX_RETRIES: int = 2
    REFLECTION_TRADE_THRESHOLD: int = 20
    MAX_CONSUMER_LAG_ALERT: int = 5_000
    ANTHROPIC_COST_ALERT_USD: float = 5.0
    FRONTEND_URL: str = "http://localhost:3000"

    # MCP auth token (optional). When set, /mcp requires Bearer auth.
    MCP_SHARED_TOKEN: str = ""

    # Market data
    MARKET_DATA_PROVIDER: str = "alpaca"
    MARKET_TICK_INTERVAL_SECONDS: float = 10.0

    # Agent trigger thresholds
    SIGNAL_EVERY_N_TICKS: int = 10
    GRADE_EVERY_N_FILLS: int = 5
    IC_UPDATE_EVERY_N_FILLS: int = 10
    REFLECT_EVERY_N_FILLS: int = 10

    # Grade system
    GRADE_LOOKBACK_N: int = 20
    GRADE_WEIGHT_ACCURACY: float = 0.35
    GRADE_WEIGHT_IC: float = 0.30
    GRADE_WEIGHT_COST: float = 0.20
    GRADE_WEIGHT_LATENCY: float = 0.15
    RETIRE_AFTER_N_GRADES: int = 3

    # IC updater
    IC_LOOKBACK_DAYS: int = 30
    IC_ZERO_THRESHOLD: float = 0.05

    # Reflection / strategy
    HYPOTHESIS_MIN_CONFIDENCE: float = 0.7

    # LLM provider routing
    LLM_PROVIDER: str = "gemini"
    # When True (default), fall back to a cloud provider if LM Studio is
    # unavailable. Set False to make LM Studio failures hard errors so the
    # system never silently routes to a cloud provider.
    LLM_FALLBACK_ENABLED: bool = Field(default=True)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GEMINI_API_KEY: str | None = Field(default=None)
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # Alpaca - use paper trading keys from alpaca.markets
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_PAPER: bool = True  # True = paper trading, False = live real money
    # Paper base URL: https://paper-api.alpaca.markets
    # Live base URL: https://api.alpaca.markets
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
    ALPACA_WS_URL: str = "wss://stream.data.alpaca.markets/v2/iex"

    # LM Studio / LM Link — local GPU inference (optional, non-blocking)
    LM_STUDIO_ENABLED: bool = Field(default=False)
    # Full base URL override — when set, takes precedence over HOST+PORT.
    # Example: LM_STUDIO_BASE_URL=http://localhost:1234/v1
    # Leave empty to use LM_STUDIO_HOST + LM_STUDIO_PORT instead.
    LM_STUDIO_BASE_URL: str = Field(default="")
    LM_STUDIO_HOST: str = "127.0.0.1"
    LM_STUDIO_PORT: int = 1234
    LM_STUDIO_MODEL: str = ""
    LM_STUDIO_TIMEOUT_SECONDS: int = 180
    # When Tailscale runs in userspace-networking mode (--outbound-http-proxy-listen),
    # set this to the HTTP CONNECT proxy URL so httpx can reach the Tailscale peer.
    # Example: LM_STUDIO_PROXY_URL=http://127.0.0.1:1055
    # Leave empty when LM Studio is local (same machine) or when Tailscale uses
    # kernel networking (TUN device).  Never set this to the LM Studio base URL.
    LM_STUDIO_PROXY_URL: str = Field(default="")
    # Task-specific token budgets — override via env vars on Render
    LM_STUDIO_MAX_TOKENS_ANALYSIS: int = Field(default=4096)
    LM_STUDIO_MAX_TOKENS_EXECUTION: int = Field(default=4096)
    LM_STUDIO_MAX_TOKENS_HEALTH_CHECK: int = Field(default=256)
    LM_LINK_ENABLED: bool = Field(default=False)
    LM_LINK_DEVICE_NAME: str = ""
    LM_LINK_TOKEN: str = Field(default="")

    # Optional - kept for backwards compatibility
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    OPENAI_API_KEY: str | None = Field(default=None)
    OPENAI_MODEL: str = "gpt-4o-mini"

    API_SECRET_KEY: str | None = Field(default=None)
    NODE_ENV: str = "development"
    # Render sets this automatically — used for self-ping keep-alive
    RENDER_EXTERNAL_URL: str | None = Field(default=None)
    NEXT_PUBLIC_APP_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: str = "http://localhost:3000,https://*.vercel.app,https://*.onrender.com,https://trading-control-khaki.vercel.app"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1,*.vercel.app,*.onrender.com"
    API_TIMEOUT_MS: int = 30000
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_MS: int = 250
    LOG_LEVEL: str = "INFO"
    # PERSISTENCE_MODE removed - now automatic: try DB, if fails use memory

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
        # Production permits DATABASE_URL to be empty when memory mode is
        # explicitly requested (e.g. the platform DB is offline and the
        # operator wants to run Redis-only without DNS noise on every health
        # check).
        if self.NODE_ENV == "production" and not self.DATABASE_URL and not self.USE_MEMORY_MODE:
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
