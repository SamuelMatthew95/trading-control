"""Application startup / shutdown orchestration for the FastAPI app.

Extracted from ``api/main.py`` so the entrypoint module stays a thin ASGI
surface (app construction, middleware, router registration) while the heavy
lifespan wiring lives here, decomposed into focused, individually-readable
steps instead of one 260-line function:

    _init_persistence       — Postgres init w/ backoff, else memory-mode fallback
    _init_redis             — Redis client + RedisStore singleton
    _probe_lmstudio         — optional local-inference health probe (non-blocking)
    _build_agents           — construct the agent fleet
    _start_background_tasks — price poller, keep-alive, backtest refresh
    lifespan                — the asynccontextmanager that sequences the above
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI

from api.config import settings
from api.constants import FieldName
from api.database import engine, get_settings_info, init_database, test_database_connection
from api.events.bus import EventBus, ensure_all_streams_ready
from api.events.dlq import DLQManager
from api.in_memory_store import InMemoryStore
from api.mcp.server import mcp_lifespan_context
from api.observability import log_structured
from api.redis_client import close_redis, get_redis
from api.routes.backtest import run_backtest_refresh_loop
from api.runtime_state import set_db_available, set_runtime_store
from api.services.agent_state import AGENT_NAMES, AgentStateRegistry
from api.services.agent_supervisor import AgentSupervisor
from api.services.agents.pipeline_agents import (
    ChallengerAgent,
    GradeAgent,
    ICUpdater,
    NotificationAgent,
    ReflectionAgent,
    StrategyProposer,
)
from api.services.agents.proposal_applier import ProposalApplier
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.agents.risk_guardian import RiskGuardian
from api.services.event_pipeline import EventPipeline
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine
from api.services.lmstudio_provider import (
    _is_lmstudio_effectively_enabled,
)
from api.services.lmstudio_provider import (
    check_health as lm_studio_check_health,
)
from api.services.lmstudio_provider import (
    log_startup_config as lm_studio_log_startup_config,
)
from api.services.prompt_store import PromptStore, set_prompt_store
from api.services.redis_store import RedisStore, set_redis_store
from api.services.signal_generator import SignalGenerator
from api.services.websocket_broadcaster import get_broadcaster
from api.workers.price_poller import poll_prices
from backtest.challenger import BASELINE_STRATEGY
from backtest.strategies import STRATEGIES

_KEEP_ALIVE_INTERVAL = 10 * 60  # 10 minutes — prevents Render spin-down


async def _keep_alive() -> None:
    """Ping our own /health every 10 min so Render never spins us down.

    Render sets RENDER_EXTERNAL_URL automatically on deployed services; no-ops
    in local dev where the env var is absent.
    """
    base_url = settings.RENDER_EXTERNAL_URL
    if not base_url:
        return  # not on Render — nothing to do
    url = f"{base_url.rstrip('/')}/health"
    await asyncio.sleep(60)  # let the app fully start before the first ping
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
            log_structured("debug", "keep_alive_ping", url=url, status=resp.status_code)
        except Exception:
            log_structured("warning", "keep_alive_ping_failed", url=url, exc_info=True)
        await asyncio.sleep(_KEEP_ALIVE_INTERVAL)


async def _init_persistence(app: FastAPI) -> None:
    """Initialise Postgres with exponential backoff, else fall back to memory mode."""
    if settings.USE_MEMORY_MODE:
        log_structured(
            "info",
            "database_skipped_use_memory_mode",
            event_name="database_skipped_use_memory_mode",
        )
        db_ok = False
    else:
        db_ok = False
        delays = [2, 4, 8]
        for attempt, delay in enumerate([0, *delays], start=1):
            if delay > 0:
                log_structured(
                    "info", "database_init_retry", attempt=attempt, backoff_seconds=delay
                )
                await asyncio.sleep(delay)
            try:
                await init_database()
                if await test_database_connection():
                    db_ok = True
                    break
            except Exception:
                log_structured(
                    "warning",
                    "database_init_attempt_failed",
                    attempt=attempt,
                    max_attempts=len(delays) + 1,
                    exc_info=True,
                )

    if db_ok:
        app.state.db_available = True
        set_db_available(True)
        app.state.in_memory_store.last_health = "db_ok"
        log_structured("info", "database_initialized_successfully")
    else:
        set_db_available(False)
        app.state.in_memory_store.last_health = "db_down"
        app.state.in_memory_store.add_notification(
            "Database connection failed after retries. Running in in-memory fallback mode.",
            level="warning",
            notification_type="startup",
        )
        with suppress(Exception):
            engine.dispose()
        log_structured(
            "warning",
            "database_connection_failed_using_memory",
            event_name="database_connection_failed_using_memory",
        )


async def _init_redis(app: FastAPI):
    """Connect Redis and install the RedisStore singleton (REST persistence)."""
    redis_client = await get_redis()
    app.state.redis_client = redis_client
    redis_store = RedisStore(redis_client)
    app.state.redis_store = redis_store
    set_redis_store(redis_store)
    # Install the self-evolving prompt store so ReasoningAgent can read the
    # learned adaptive directive and ProposalApplier can promote new ones.
    prompt_store = PromptStore(redis_client)
    app.state.prompt_store = prompt_store
    set_prompt_store(prompt_store)
    log_structured(
        "info",
        "redis_connected",
        event_name="redis_connected",
        msg_id="none",
        event_type="system",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return redis_client


async def _probe_lmstudio() -> None:
    """Optional local-inference health probe. Non-blocking; never stops startup."""
    if _is_lmstudio_effectively_enabled():
        lm_studio_log_startup_config()
        try:
            lm_ok = await asyncio.wait_for(lm_studio_check_health(), timeout=10.0)
        except asyncio.TimeoutError:
            lm_ok = False
        log_structured(
            "info",
            "lmstudio_startup_check",
            lm_studio_enabled=True,
            lm_link_enabled=settings.LM_LINK_ENABLED,
            device_name=settings.LM_LINK_DEVICE_NAME or None,
            model=settings.LM_STUDIO_MODEL or None,
            local_inference_healthy=lm_ok,
            fallback_provider=settings.LLM_PROVIDER,
            degraded_mode=not lm_ok,
        )
    else:
        log_structured(
            "info",
            "lmstudio_startup_check",
            lm_studio_enabled=False,
            local_inference_healthy=False,
            fallback_provider=settings.LLM_PROVIDER,
            degraded_mode=False,
        )


def _build_agents(event_bus, dlq_manager, redis_client, agent_state, paper_broker) -> list:
    """Construct the full agent fleet (order matters only for logging)."""
    grade_agent = GradeAgent(event_bus, dlq_manager, agent_state=agent_state)
    reflection_agent = ReflectionAgent(event_bus, dlq_manager, agent_state=agent_state)
    # Inject grader so reflection can read the live eval buffer for quant mistake
    # clusters without an extra DB round-trip.
    reflection_agent._grade_agent = grade_agent

    return [
        SignalGenerator(event_bus, dlq_manager, agent_state=agent_state),
        ReasoningAgent(event_bus, dlq_manager, redis_client, agent_state=agent_state),
        ExecutionEngine(
            event_bus, dlq_manager, redis_client, paper_broker, agent_state=agent_state
        ),
        grade_agent,
        ICUpdater(event_bus, dlq_manager, redis_client, agent_state=agent_state),
        reflection_agent,
        StrategyProposer(event_bus, dlq_manager, agent_state=agent_state),
        NotificationAgent(event_bus, dlq_manager, redis_client, agent_state=agent_state),
        # One shadow ChallengerAgent per candidate strategy: each consumes the live
        # execution / trade_performance streams, is graded, and places NO orders —
        # it registers at SHADOW in the lifecycle. This is how non-baseline
        # strategies get hooked up without skipping straight to live.
        *[
            ChallengerAgent(
                event_bus,
                dlq_manager,
                challenger_config={FieldName.STRATEGY: strategy_name},
                agent_state=agent_state,
            )
            for strategy_name in STRATEGIES
            if strategy_name != BASELINE_STRATEGY
        ],
        # ProposalApplier closes the learning loop — it consumes STREAM_PROPOSALS
        # and applies the actions to Redis control-plane keys that ExecutionEngine
        # and ReasoningAgent read. Without it, low grades become rows nobody acts on.
        ProposalApplier(event_bus, dlq_manager, redis_client, agent_state=agent_state),
    ]


def _start_background_tasks(app: FastAPI) -> None:
    """Launch the long-running background tasks (poller, keep-alive, backtest)."""
    app.state.poller_task = asyncio.create_task(poll_prices(), name="price-poller")
    log_structured("info", "price_poller_started", mode="background_task")

    app.state.keep_alive_task = asyncio.create_task(_keep_alive(), name="keep-alive")

    # Backtest dashboard: warm the cache on boot, then refresh it hourly.
    app.state.backtest_refresh_task = asyncio.create_task(
        run_backtest_refresh_loop(), name="backtest-refresh"
    )


async def _shutdown(app: FastAPI, pipeline: EventPipeline | None, broadcaster) -> None:
    """Tear down tasks, agents, and connections in reverse dependency order."""
    for task_name in ("poller_task", "keep_alive_task", "backtest_refresh_task"):
        task = getattr(app.state, task_name, None)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    supervisor = getattr(app.state, "supervisor", None)
    if supervisor is not None:
        await supervisor.stop()
    for agent in reversed(getattr(app.state, "agents", [])):
        await agent.stop()
    risk_guardian = getattr(app.state, "risk_guardian", None)
    if risk_guardian is not None:
        await risk_guardian.stop()
    if pipeline is not None:
        await pipeline.stop()
    await broadcaster.stop()
    await close_redis()
    await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Sequence startup, yield to serve requests, then tear everything down."""
    app.state.db_engine = engine
    app.state.in_memory_store = InMemoryStore()
    set_runtime_store(app.state.in_memory_store)
    app.state.db_available = False
    set_db_available(False)
    app.state.redis_client = None
    app.state.event_bus = None
    app.state.event_pipeline = None
    app.state.dlq_manager = None
    app.state.agent_state = None
    app.state.agents = []

    pipeline: EventPipeline | None = None
    broadcaster = get_broadcaster()
    agent_state = AgentStateRegistry()

    mcp_lifespan_cm = mcp_lifespan_context()
    await mcp_lifespan_cm.__aenter__()

    try:
        await _init_persistence(app)
        redis_client = await _init_redis(app)
        await _probe_lmstudio()

        event_bus = EventBus(redis_client)
        dlq_manager = DLQManager(redis_client, event_bus)

        # STARTUP BARRIER: every stream + consumer group must exist before any
        # consumer starts. ensure_all_streams_ready() creates, verifies, and
        # self-heals any missing groups atomically.
        await ensure_all_streams_ready(redis_client)
        log_structured(
            "info",
            "redis_startup_barrier_passed",
            event_name="redis_startup_barrier_passed",
            event_type="system",
            msg_id="none",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        await broadcaster.start(redis_client)
        log_structured(
            "info",
            "websocket_started",
            event_name="websocket_started",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        pipeline = EventPipeline(event_bus, broadcaster, dlq_manager, agent_state=agent_state)
        await pipeline.start()

        app.state.event_bus = event_bus
        app.state.event_pipeline = pipeline
        app.state.websocket_broadcaster = broadcaster
        app.state.dlq_manager = dlq_manager
        app.state.agent_state = agent_state

        paper_broker = PaperBroker(redis_client)
        _start_background_tasks(app)

        agents = _build_agents(event_bus, dlq_manager, redis_client, agent_state, paper_broker)
        for agent in agents:
            await agent.start()
            log_structured(
                "info",
                "agent_subscription_ready",
                agent=agent.name,
                stream=getattr(agent, "stream", None),
                streams=getattr(agent, "streams", None),
            )
        app.state.agents = agents

        # RiskGuardian: periodic position monitor (stop-loss, take-profit, daily loss).
        risk_guardian = RiskGuardian(event_bus, redis_client)
        await risk_guardian.start()
        app.state.risk_guardian = risk_guardian

        # AgentSupervisor: detects crashed agent tasks and restarts them.
        # RiskGuardian is included so the stop-loss / daily-loss monitor is
        # restarted too if its task ever dies — it is the one safety-critical
        # background task we cannot afford to leave unmonitored.
        supervisor = AgentSupervisor(event_bus, [*agents, risk_guardian])
        await supervisor.start()
        app.state.supervisor = supervisor

        await broadcaster.broadcast(
            {
                FieldName.TYPE: "system",
                FieldName.STATUS: "running",
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            }
        )

        log_structured(
            "info",
            "system_startup_status",
            event_name="system_startup_status",
            redis="ok",
            pipeline="started",
            websocket="ready",
            agents_connected=len(app.state.agents),
            agents=list(AGENT_NAMES),
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
            environment=settings.NODE_ENV,
            config_source=get_settings_info().get(FieldName.CONFIG_SOURCE),
            database_mode="connected" if app.state.db_available else "in_memory_fallback",
        )
        yield
    except Exception:
        log_structured(
            "error",
            "startup_failed",
            event_name="startup_failed",
            event_type="system",
            msg_id="none",
            timestamp=datetime.now(timezone.utc).isoformat(),
            exc_info=True,
        )
        raise
    finally:
        await _shutdown(app, pipeline, broadcaster)
        await mcp_lifespan_cm.__aexit__(None, None, None)
