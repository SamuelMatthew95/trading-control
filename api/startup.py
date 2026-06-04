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
from api.constants import VALID_SYMBOLS, FieldName
from api.database import engine, get_settings_info, init_database, test_database_connection
from api.events.bus import EventBus, ensure_all_streams_ready
from api.events.dlq import DLQManager
from api.in_memory_store import InMemoryStore
from api.main_state import set_services
from api.mcp.server import mcp_lifespan_context
from api.observability import log_structured
from api.redis_client import close_redis, get_redis
from api.routes.backtest import run_backtest_refresh_loop
from api.runtime_state import (
    get_runtime_store,
    is_db_available,
    set_db_available,
    set_runtime_store,
)
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
from api.services.challenger_spawner import ChallengerSpawner
from api.services.config_overrides import apply_parameter_overrides
from api.services.event_pipeline import EventPipeline
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine
from api.services.feedback_service import FeedbackService
from api.services.learning_service import LearningService
from api.services.lmstudio_provider import (
    _is_lmstudio_effectively_enabled,
)
from api.services.lmstudio_provider import (
    check_health as lm_studio_check_health,
)
from api.services.lmstudio_provider import (
    log_startup_config as lm_studio_log_startup_config,
)
from api.services.multi_agent_orchestrator import MultiAgentOrchestrator
from api.services.prompt_store import PromptStore, set_prompt_store
from api.services.redis_store import RedisStore, set_redis_store
from api.services.signal_generator import SignalGenerator
from api.services.trading import TradingService
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


async def _hydrate_positions_from_broker(broker: PaperBroker) -> None:
    """In memory mode, seed the InMemoryStore position mirror from the broker.

    The PaperBroker (Redis) persists positions across restarts, but a fresh
    InMemoryStore starts empty — so without this the dashboard would show no
    positions after a redeploy until the next fill, and a SELL of a carried-over
    long would look like it came from nowhere. Mirrors the broker (the single
    source of truth) for every supported symbol on boot. Best effort: a Redis
    hiccup on one symbol never blocks startup.
    """
    if is_db_available():
        return
    store = get_runtime_store()
    hydrated = 0
    for symbol in VALID_SYMBOLS:
        try:
            position = await broker.get_position(symbol)
        except Exception:
            log_structured("warning", "position_hydration_failed", symbol=symbol, exc_info=True)
            continue
        store.mirror_broker_position(symbol, position)
        if store.has_active_position(symbol):
            hydrated += 1
    if hydrated:
        log_structured("info", "positions_hydrated_from_broker", count=hydrated)


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


def _wire_shared_services(app: FastAPI, agents: list, paper_broker: PaperBroker) -> None:
    """Populate the route-facing service registry and app.state singletons.

    REST routes (analyze, feedback, performance, positions, pnl) resolve their
    dependencies through ``api.main_state`` getters, so this must run once at
    startup. The TradingService wraps a MultiAgentOrchestrator for the synchronous
    ``/analyze`` path; without an Anthropic key the orchestrator uses its
    deterministic reasoning model, so /analyze still returns a real decision
    offline.

    The live ReasoningAgent is also published on ``app.state.reasoning_agent`` so
    the idiomatic dependency in ``api.dependencies`` (``get_reasoning_agent``)
    resolves the exact instance the pipeline runs, instead of 503-ing. Other
    agents stay reachable via ``app.state.agents`` (the canonical list other
    routes already filter), so we don't duplicate per-agent registries here.
    """
    try:
        orchestrator = MultiAgentOrchestrator(api_key=settings.ANTHROPIC_API_KEY or None)
    except Exception:
        # Never let orchestrator construction block startup — /analyze falls back
        # to MOCK MODE (a valid degraded FLAT decision) when the orchestrator is
        # absent.
        log_structured("warning", "orchestrator_init_failed_mock_mode", exc_info=True)
        orchestrator = None
    trading_service = TradingService(orchestrator)

    set_services(
        trading_service=trading_service,
        feedback_service=FeedbackService(),
        learning_service=LearningService(),
        paper_broker=paper_broker,
    )

    # Publish the live ReasoningAgent on app.state so api.dependencies can inject
    # it (the agent is event-driven; this is the read handle for REST/introspection).
    reasoning_agent = next((a for a in agents if isinstance(a, ReasoningAgent)), None)
    app.state.reasoning_agent = reasoning_agent

    log_structured(
        "info",
        "shared_services_wired",
        trading_service=True,
        orchestrator=orchestrator is not None,
        paper_broker=True,
        reasoning_agent=reasoning_agent is not None,
    )


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
    # Apply any merged config overrides (auto-PR GitOps) over settings before
    # anything reads them. Defensive: bad/unknown overrides are skipped.
    applied_overrides = apply_parameter_overrides(settings)
    if applied_overrides:
        log_structured("info", "config_overrides_applied", params=applied_overrides)

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
        # Seed the in-memory position mirror from the broker (the source of
        # truth) so a restart in memory mode doesn't blank the dashboard's
        # positions until the next fill.
        await _hydrate_positions_from_broker(paper_broker)
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

        # Wire the shared service registry (api.main_state) so the analyze /
        # feedback / performance / positions / pnl routes operate on the same
        # live PaperBroker, runtime store, and pipeline agents.
        _wire_shared_services(app, agents, paper_broker)

        # Wire the dynamic challenger spawner (shared by the dashboard route and
        # an approved NEW_AGENT proposal) onto the live agents list + the applier.
        spawner = ChallengerSpawner(event_bus, dlq_manager, agents, agent_state)
        app.state.challenger_spawner = spawner
        for agent in agents:
            if isinstance(agent, ProposalApplier):
                agent.spawner = spawner

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
