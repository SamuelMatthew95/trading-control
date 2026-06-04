"""Shared application service registry.

The FastAPI lifespan (``api/startup.py``) constructs the live service stack and
calls :func:`set_services` once at startup. Route modules resolve their
dependencies through the getters here so they always operate on the same wired
instances the rest of the app uses.

Scope: this registry holds only the services that REST routes resolve through
it — the synchronous ``TradingService`` (``/analyze``), the ``FeedbackService``
(``/feedback`` + ``/memory``), the ``LearningService`` (``/api/performance``),
and the ``PaperBroker`` (``/positions`` + ``/pnl``). Other shared singletons
have their own canonical homes and must NOT be duplicated here:

- the runtime store → ``api.runtime_state.get_runtime_store()``
- the live agent fleet / event bus / Redis → ``request.app.state`` via the
  dependency helpers in ``api.dependencies`` (idiomatic FastAPI access).

Design rule: getters NEVER raise. A route must degrade gracefully (return a
stub / degraded payload) when a backing service was not wired — it must never
500 just because startup ran in a reduced mode (e.g. DB down, Redis-only).
``trading_service`` / ``feedback_service`` / ``learning_service`` fall back to
lazily-built in-memory instances so their routes stay importable and responsive
even before ``set_services`` runs (e.g. unit tests importing the app directly).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.services.feedback_service import FeedbackService
from api.services.learning_service import LearningService
from api.services.trading import TradingService

if TYPE_CHECKING:  # avoid runtime circular imports — these are only type hints
    from api.services.execution.brokers.paper import PaperBroker

# --- Active service singletons (populated by set_services at startup) ---------
_trading_service: TradingService | None = None
_feedback_service: FeedbackService | None = None
_learning_service: LearningService | None = None
_paper_broker: PaperBroker | None = None

# Lazily-built degraded fallbacks so getters never raise before startup wiring.
_default_trading_service: TradingService | None = None
_default_feedback_service: FeedbackService | None = None
_default_learning_service: LearningService | None = None


def set_services(
    *,
    trading_service: TradingService | None = None,
    feedback_service: FeedbackService | None = None,
    learning_service: LearningService | None = None,
    paper_broker: PaperBroker | None = None,
) -> None:
    """Wire the live service stack. Called once from the startup lifespan.

    Every argument is optional so a reduced-mode startup can wire only what it
    has. Passing ``None`` leaves the existing value untouched rather than
    clearing it, so partial re-wiring is safe.
    """
    global _trading_service, _feedback_service, _learning_service, _paper_broker

    if trading_service is not None:
        _trading_service = trading_service
    if feedback_service is not None:
        _feedback_service = feedback_service
    if learning_service is not None:
        _learning_service = learning_service
    if paper_broker is not None:
        _paper_broker = paper_broker


def get_trading_service() -> TradingService:
    """Return the wired trading service, or a mock-mode fallback (never raises)."""
    if _trading_service is not None:
        return _trading_service
    global _default_trading_service
    if _default_trading_service is None:
        # No orchestrator -> TradingService runs in MOCK MODE and returns a
        # valid degraded FLAT decision so /analyze answers with HTTP 200.
        _default_trading_service = TradingService(None)
    return _default_trading_service


def get_feedback_service() -> FeedbackService:
    """Return the wired feedback service, or a default in-memory stub."""
    if _feedback_service is not None:
        return _feedback_service
    global _default_feedback_service
    if _default_feedback_service is None:
        _default_feedback_service = FeedbackService()
    return _default_feedback_service


def get_learning_service() -> LearningService:
    """Return the wired learning service, or a default in-memory stub."""
    if _learning_service is not None:
        return _learning_service
    global _default_learning_service
    if _default_learning_service is None:
        _default_learning_service = LearningService()
    return _default_learning_service


def get_paper_broker() -> PaperBroker | None:
    """Return the wired PaperBroker, or ``None`` when not yet started.

    Positions/PnL routes fall back to the runtime-store mirror when this is
    ``None`` (very early startup / unit tests), so the absence is handled
    gracefully rather than raising.
    """
    return _paper_broker
