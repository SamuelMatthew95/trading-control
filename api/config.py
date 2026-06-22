"""Application settings with strict validation for production runtime."""

from __future__ import annotations

from pydantic import (
    Field,
    PostgresDsn,
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
    # Run the agent-grade cycle after every closed trade. GradeAgent grading is
    # fully deterministic (no LLM, no token cost), so per-fill cadence is cheap.
    # At the old default of 5 the cycle never reached its trigger on this paper
    # system (a handful of closed trades a day), so the dashboard's grade history
    # stayed empty, closed trades were never back-filled with a grade, and the
    # grade-cycle-gated proposal producers (tool governance, SystemArchitect's
    # grade-trajectory observer) never fired — the same starvation already fixed
    # for REFLECT_EVERY_N_FILLS (10→1). Destructive grade actions stay protected
    # by the separate GRADE_ACTION_MIN_FILLS statistical-significance gate.
    GRADE_EVERY_N_FILLS: int = 1
    IC_UPDATE_EVERY_N_FILLS: int = 10
    # Reflect every N closed trades. Set to 1 so learning is INCREMENTAL: the
    # ReflectionAgent reflects after each closed trade, carrying the previous
    # reflection forward (compare → refine → improve) rather than waiting for a
    # batch. At the old default of 10 it never reached the trigger (this paper
    # system closes a handful of trades a day), so StrategyProposer never ran.
    REFLECT_EVERY_N_FILLS: int = 1
    # Minimum buffered fills before the first reflection runs. 1 = start learning
    # from the very first closed trade, then accumulate.
    REFLECT_MIN_FILLS: int = 1
    # Cost governance: minimum seconds between automatic reflections. A reflection
    # fires a chain of LLM calls, so without this a burst of closed trades (with
    # REFLECT_EVERY_N_FILLS=1) would fan out into a call per trade and spike spend
    # / rate-limits. The operator reflect-now endpoint bypasses this.
    REFLECTION_MIN_INTERVAL_SECONDS: float = 300.0
    # Periodic reflection safety-net interval (seconds). Triggers a reflection
    # when new fills have arrived since the last one — and once shortly after
    # startup on seeded history, so a restart produces proposals without waiting
    # for a fresh trade. 0 disables. Bounded by the proposal dedup/daily cap.
    REFLECTION_PERIODIC_SECONDS: int = 1_800
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
    # When True an applied challenger promotion also GRADUATES the strategy one
    # lifecycle stage (SHADOW -> CANARY) in the strategy registry, so a winning
    # shadow becomes a first-class canary candidate instead of staying a
    # decorative shadow forever. Pure registry state — still places no live
    # orders. Set False to keep promotions to a prompt-directive bias only.
    CHALLENGER_GRADUATE_TO_CANARY: bool = True

    # No-trade time window (proposal #339 — "avoid trading in the morning").
    # When enabled, NEW long entries (BUY) are blocked while the current
    # Eastern-Time wall clock falls within [START, END) — e.g. the volatile
    # first 30 minutes after the 09:30 ET open. Exits (SELL) are NEVER gated, so
    # stop-loss / take-profit / trailing closes can always de-risk during the
    # window (same long-only-exit safety stance as the cooling-off gate).
    # Off by default so live behavior is unchanged until an operator opts in.
    # Bounds are 24-hour "HH:MM" in America/New_York; a window whose START is
    # later than its END wraps past midnight. START == END (or malformed) =
    # no window.
    NO_TRADE_WINDOW_ENABLED: bool = False
    NO_TRADE_WINDOW_START_ET: str = "09:30"
    NO_TRADE_WINDOW_END_ET: str = "10:00"

    # Grade system
    GRADE_LOOKBACK_N: int = 20
    GRADE_WEIGHT_ACCURACY: float = 0.35
    GRADE_WEIGHT_IC: float = 0.30
    GRADE_WEIGHT_COST: float = 0.20
    GRADE_WEIGHT_LATENCY: float = 0.15
    RETIRE_AFTER_N_GRADES: int = 3
    # Statistical-significance gate: minimum graded fills before the GradeAgent
    # may take a CAPITAL-AFFECTING action (signal-weight cut / suspension /
    # retirement→pause). Below this, win-rate and IC are noise — acting on them
    # can hard-pause the whole system off a handful of trades (the deadlock we
    # hit). The grade is still computed and shown; only destructive actions wait.
    GRADE_ACTION_MIN_FILLS: int = 20

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
    # Periodic System Architect pass — a deterministic (no-LLM) backstop that
    # reviews accumulated system state (per-model net ROI, the recent grade
    # trajectory) and emits a SMALL number of evidence-tiered, fully-briefed
    # strategic proposals the per-trade reflection loop misses. It is NOT a stream
    # consumer (no always-on Redis connection — respects the Redis pool-sizing
    # invariant); a startup background loop calls it on this interval. It shares
    # the same creation guardrails (daily cap + dedup) so it never spams the
    # queue. SYSTEM_ARCHITECT_INTERVAL_SECONDS=0 (or _ENABLED=False) disables it.
    SYSTEM_ARCHITECT_ENABLED: bool = True
    SYSTEM_ARCHITECT_INTERVAL_SECONDS: int = 3_600

    # GitOps auto-PR — when a PARAMETER_CHANGE proposal is applied, open a real
    # PR that edits a CONFIG file (never raw code), version-controlled + human-
    # reviewed. Activates only when a token + repo are present (GITHUB_TOKEN is
    # set in Render); locally/in tests it is a safe dry-run no-op.
    GITHUB_TOKEN: str = ""
    GITHUB_REPO: str = "SamuelMatthew95/trading-control"  # "owner/repo"
    GITHUB_AUTOPR_ENABLED: bool = True
    GITHUB_AUTOPR_BASE_BRANCH: str = "main"

    # Gate auto-filed feature issues (CODE_CHANGE / REGIME_ADJUSTMENT / NEW_AGENT)
    # on evidence sufficiency. The learning loop fires a handful of trades a day,
    # so it routinely emits proposals whose OWN evidence block is flagged
    # ``evidence_sufficient: false`` (n=1..5, no backtest). Filing each as a GitHub
    # issue created recurring, unactionable human-triage load (issues #322/#324/
    # #334/#341/#345/#346/#349 were all closed not-planned for exactly this).
    # When True, an insufficient-evidence proposal is still recorded as a
    # watch-item (proposal stream + dashboard, the loop is never starved) but is
    # NOT escalated to a GitHub issue until a backtest-backed sample firms up.
    # Proposals carrying no evidence block (structural architect work) are
    # unaffected — they are filed as before. Set False to restore filing every
    # proposal as an issue.
    PROPOSAL_ISSUE_REQUIRE_SUFFICIENT_EVIDENCE: bool = True

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
    # Verified against ai.google.dev (June 2026): gemini-3.5-flash is the current
    # GA Flash model and the API default. gemini-1.5/2.0/2.5-flash are retired or
    # deprecating — using them 404s every call. Override via GEMINI_MODEL env.
    GEMINI_MODEL: str = "gemini-3.5-flash"

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
    # Managed backends (SigNoz Cloud, Grafana Cloud): set the ingest URL,
    # OTEL_EXPORTER_OTLP_INSECURE=false, and the auth header, e.g.
    #   OTEL_EXPORTER_OTLP_HEADERS="signoz-ingestion-key=<token>"
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "trading-control"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    # "grpc" (local collectors, port 4317) or "http/protobuf" (SigNoz Cloud's
    # documented protocol, port 443/4318).
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "grpc"
    # Plaintext gRPC is for local collectors only; cloud backends need TLS.
    OTEL_EXPORTER_OTLP_INSECURE: bool = True
    # Standard OTel format: comma-separated key=value pairs.
    OTEL_EXPORTER_OTLP_HEADERS: str = ""
    # Seconds between business-gauge refreshes (PnL / positions / balance).
    OTEL_GAUGE_POLL_SECONDS: float = 30.0
    # Auto-instrument Redis COMMANDS (one span per Redis call). OFF by default.
    # RedisInstrumentor wraps EVERY command on the single shared
    # BlockingConnectionPool — including the ~14 always-on XREADGROUP/XREAD
    # BLOCK loops that fire ~10x/sec each. That is the highest-volume,
    # lowest-value span source in the system (a "blocking read returned
    # nothing" span per consumer per 100ms) and it piles overhead onto the
    # scarcest shared resource: the pooled connections whose exhaustion already
    # wedged the dashboard (see docs/troubleshooting/system-routes.md ->
    # "Redis command instrumentation on the always-on consumer hot path").
    # Trade-lifecycle latency is already captured by agent_process_span /
    # traced_broker_call / the SQLAlchemy query listener, so the Redis hot path
    # stays uninstrumented without losing trace coverage. Set true only to
    # actively debug Redis itself.
    OTEL_INSTRUMENT_REDIS: bool = False
    # Runtime telemetry drift auditor (governance Layer B). OFF by default.
    # When on, observed trading.* attribute keys are diffed against
    # TELEMETRY_SCHEMA on an interval; unknown keys / cardinality-budget breaches
    # emit the bounded telemetry_schema_drift_total counter + a structured log.
    OTEL_DRIFT_AUDIT_ENABLED: bool = False
    OTEL_DRIFT_AUDIT_INTERVAL_SECONDS: float = 300.0
    # B2 (SigNoz-side) source — observed label keys + value-cardinality from
    # SigNoz's query API. Empty URL => B2 is a no-op (B1 app-side still runs);
    # a thin adapter you wire to your deployment's query endpoint/auth.
    SIGNOZ_QUERY_URL: str = ""
    SIGNOZ_QUERY_KEY: str = ""

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

    # Redis connection pool (tune for Render Redis plan limits).
    # The whole process shares ONE BlockingConnectionPool. It must cover the
    # ~14 ALWAYS-ON blocking stream-reader loops that each hold a pooled
    # connection ~continuously (XREADGROUP/XREAD BLOCK 100ms, then re-acquire):
    # 9 pipeline agents + 3 challenger agents + the EventPipeline broadcast
    # consumer + the WebSocket broadcaster xread loop. At the old cap of 20
    # those loops left only ~6 connections for request/response traffic (REST
    # handlers on a dashboard refresh, per-agent heartbeats, the price poller's
    # per-symbol GETs, RiskGuardian/gauge-poller scans, kill-switch/order-lock
    # reads, DLQ ops), so a refresh burst starved callers past the wait timeout
    # and raised ConnectionError("No connection available") from get_connection.
    # 50 keeps the always-on loops plus a full refresh burst comfortably served.
    # Render Key Value plan client limits (per Render's published plan specs —
    # verify in the dashboard before changing plans): free=50, starter=250.
    # We run plan "starter" (render.yaml) with a single gunicorn worker (-w 1),
    # so this cap IS the process-wide ceiling: 50 of 250 leaves ample margin.
    # NEVER set this at-or-above the plan limit — on the free plan 50 would sit
    # exactly at the ceiling with zero room for redis-cli or monitoring.
    # Guardrail: tests/core/test_redis_client.py::
    # test_max_connections_covers_worst_case_always_on_consumers derives the
    # worst-case always-on consumer count from the real fleet construction and
    # fails CI if this cap ever drops below it plus request-burst headroom.
    REDIS_MAX_CONNECTIONS: int = 50
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
