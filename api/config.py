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
    # When the reasoning LLM is unavailable, FAIL CLOSED: emit REJECT (no order),
    # recorded + visible on the dashboard — never a naive momentum buy/sell. The
    # constitution is capital-preservation-first; guessing direction without the
    # brain loses money. "use_last_reflection" (reuse the last LLM guidance) and
    # "skip_reasoning" (naive directional) remain opt-in for operators who want them.
    LLM_FALLBACK_MODE: str = "reject_signal"
    # Level-3 data-plane / control-plane split — who decides per signal:
    #   "llm" (default): the LLM decides; the deterministic policy runs in SHADOW
    #         alongside it (agreement is logged) and is the outage fallback.
    #   "policy": the deterministic data-plane policy decides every signal; the LLM
    #         never blocks the critical path (it tunes params on the control plane).
    #   "hybrid": LLM-primary, with the policy as the always-on safety net on any
    #         LLM failure — never goes dark.
    DECISION_MODE: str = "llm"
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

    # Price-poller cadence — separate per asset class. Crypto polls 24/7; the
    # stock interval only applies while the NYSE/NASDAQ session is open (the
    # MarketStatusService gates stock fetches otherwise, so stocks go idle
    # overnight/weekends/holidays). Raising these reduces Alpaca + Redis load.
    CRYPTO_POLL_INTERVAL_SECONDS: float = 30.0
    STOCK_POLL_INTERVAL_SECONDS: float = 60.0

    # Agent trigger thresholds
    SIGNAL_EVERY_N_TICKS: int = 10
    GRADE_EVERY_N_FILLS: int = 5
    IC_UPDATE_EVERY_N_FILLS: int = 10
    REFLECT_EVERY_N_FILLS: int = 10
    # Per-symbol reasoning cooldown — minimum seconds between LLM reasoning
    # calls for the SAME symbol. Decouples LLM spend from raw signal volume:
    # momentum signals can fire every few seconds per symbol, and previously
    # each one woke a full LLM call (plus a self-critique call), which burned
    # the provider quota. Within the cooldown window a fresh signal reuses the
    # deterministic fallback path instead of calling the LLM. 0 disables it.
    REASONING_COOLDOWN_SECONDS: float = 60.0
    # Skip the LLM when a fresh signal's side matches the last-reasoned one and
    # its price is within this percent — a materially identical signal carries
    # no new information. 0 disables. Complements the cooldown for slow but
    # repetitive signals.
    REASONING_DEDUP_PRICE_PCT: float = 0.05
    # The ReAct self-critique is a SECOND LLM call on high-confidence buy/sells.
    # Disabled by default to halve actionable-decision LLM spend; re-enable when
    # provider budget allows and decision-quality review is worth the extra call.
    REASONING_SELF_CRITIQUE_ENABLED: bool = False
    # Behavioral promotion: when True, ReasoningAgent multiplies its
    # signal_weight_scale by the per-agent trust weight set by the
    # promotion-apply action (bounded by AGENT_TRUST_MIN/MAX). Defaults OFF so
    # per-agent grades never change live trading until an operator opts in.
    AGENT_TRUST_WEIGHTING_ENABLED: bool = False
    # Self-evolving prompt loop. When enabled, StrategyProposer asks the LLM to
    # draft an improved reasoning-node directive from each reflection's
    # winning/losing factors and emits a PROMPT_EVOLUTION proposal.
    PROMPT_EVOLUTION_ENABLED: bool = True
    # When True the ProposalApplier applies an approved/auto PROMPT_EVOLUTION
    # directly to the prompt store (the directive is always subordinate to the
    # immutable constitution and fully version-historied for rollback), closing
    # the self-improving loop autonomously. Set False to require manual apply.
    PROMPT_EVOLUTION_AUTO_APPLY: bool = True

    # When True an eligible challenger promotion (>= CHALLENGER_MIN_SHADOW_TRADES
    # closed shadow trades AND beating the live baseline) applies WITHOUT waiting
    # for an operator vote: the prompt directive is biased toward the winning
    # strategy and a follow-up shadow candidate is spawned. Safe to automate —
    # neither half places live orders or moves capital, both are versioned and
    # reversible. Set False to restore the manual approval gate on the
    # Proposals page.
    CHALLENGER_PROMOTION_AUTO_APPLY: bool = True

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
    # Proposal-creation guardrails (StrategyProposer): cap how many proposals
    # may be emitted in a single UTC day, and dedup identical candidates within
    # that day. Set to 0 to disable the cap. Keeps the review queue from being
    # flooded with repeats when reflection runs frequently.
    MAX_PROPOSALS_PER_DAY: int = 20

    # GitOps auto-PR — when a PARAMETER_CHANGE proposal is applied, open a real
    # PR that edits a CONFIG file (never raw code), version-controlled + human-
    # reviewed. Activates only when a token + repo are present (GITHUB_TOKEN is
    # set in Render); locally/in tests it is a safe dry-run no-op.
    GITHUB_TOKEN: str = ""
    GITHUB_REPO: str = "SamuelMatthew95/trading-control"  # "owner/repo"
    GITHUB_AUTOPR_ENABLED: bool = True
    GITHUB_AUTOPR_BASE_BRANCH: str = "main"

    # LLM provider routing
    LLM_PROVIDER: str = "gemini"
    # When True (default), fall back to a cloud provider if LM Studio is
    # unavailable. Set False to make LM Studio failures hard errors so the
    # system never silently routes to a cloud provider.
    LLM_FALLBACK_ENABLED: bool = Field(default=True)
    GROQ_API_KEY: str = ""
    # Two-tier Groq routing: call the capable model first, and if it is
    # throttled (429 / quota / rate-limit) transparently retry the SAME call on
    # the lighter instruct model instead of hard-failing. A hard failure made
    # every reasoning call fall back to skip_reasoning, which starved the
    # grade/IC/reflection learning loop. The instruct model has a far larger
    # rate-limit allowance and is sufficient for a clean JSON trading decision.
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_FALLBACK_MODEL: str = "llama-3.1-8b-instant"
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
    # Exact model ID shown in LM Studio UI — must match /v1/models response.
    # Default matches the verified Meta-Llama-3.1-8B instruct model on LM Studio.
    LM_STUDIO_MODEL: str = "meta-llama-3.1-8b-instruct"
    LM_STUDIO_TIMEOUT_SECONDS: int = 30
    # When Tailscale runs in userspace-networking mode (--outbound-http-proxy-listen),
    # set this to the HTTP CONNECT proxy URL so httpx can reach the Tailscale peer.
    # Example: LM_STUDIO_PROXY_URL=http://127.0.0.1:1055
    # Leave empty when LM Studio is local (same machine) or when Tailscale uses
    # kernel networking (TUN device).  Never set this to the LM Studio base URL.
    LM_STUDIO_PROXY_URL: str = Field(default="")
    # Task-specific token budgets — override via env vars on Render.
    # 256 is sufficient for a clean JSON trading decision from an instruct model.
    LM_STUDIO_MAX_TOKENS_ANALYSIS: int = Field(default=256)
    LM_STUDIO_MAX_TOKENS_EXECUTION: int = Field(default=256)
    LM_STUDIO_MAX_TOKENS_HEALTH_CHECK: int = Field(default=256)
    # Global defaults — LM_STUDIO_MAX_TOKENS_* per-task vars override these.
    LM_STUDIO_MAX_TOKENS: int = Field(default=256)
    LM_STUDIO_TEMPERATURE: float = Field(default=0.0)
    LM_STUDIO_STREAM: bool = Field(default=False)
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
    # OpenTelemetry — disabled by default; the app runs identically without
    # the SDK installed. Point the endpoint at a SigNoz / OTLP collector.
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "trading-control"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    # Seconds between business-gauge refreshes (PnL / positions / balance).
    OTEL_GAUGE_POLL_SECONDS: float = 30.0

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
    # Max seconds a caller waits for a free pooled connection before erroring.
    # With a BlockingConnectionPool this replaces the plain pool's immediate
    # ConnectionError("Too many connections") under a request burst.
    REDIS_POOL_TIMEOUT_SECONDS: float = 5.0

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
