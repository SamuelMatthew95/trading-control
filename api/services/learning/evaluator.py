"""Execution consumer that computes realized trade learning metrics."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import text

from api.db import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured

FACTOR_KEYS = (
    "ofi_score",
    "momentum_score",
    "volume_ratio",
    "composite_score",
    "volatility_score",
    "trend_score",
)


class TradeEvaluator(BaseStreamConsumer):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client):
        super().__init__(
            bus,
            dlq,
            stream="executions",
            group=DEFAULT_GROUP,
            consumer="trade-evaluator",
        )
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        order_id = str(data["order_id"])
        strategy_id = str(data["strategy_id"])
        symbol = str(data["symbol"])
        side = str(data.get("side", "buy")).lower()
        qty = float(data.get("qty", 0.0) or 0.0)
        fill_price = float(data.get("fill_price", data.get("price", 0.0)) or 0.0)
        trace_id = data.get("trace_id")
        filled_at = self._parse_timestamp(data.get("filled_at"))

        async with AsyncSessionFactory() as session:
            prior_trade = await self._fetch_prior_trade(
                session, strategy_id, symbol, order_id
            )
            signal_payload = await self._fetch_signal_payload(
                session, trace_id, strategy_id, symbol
            )
            factor_attribution = self._build_factor_attribution(signal_payload)
            pnl, holding_secs, entry_price = self._compute_trade_metrics(
                prior_trade=prior_trade,
                side=side,
                qty=qty,
                fill_price=fill_price,
                filled_at=filled_at,
            )
            market_context = {
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "trace_id": trace_id,
                "fill_price": fill_price,
                "timestamp": filled_at.isoformat(),
                "vwap_plan": data.get("vwap_plan"),
            }

            await session.execute(
                text(
                    "INSERT INTO trade_performance (order_id, symbol, pnl, holding_secs, entry_price, exit_price, market_context, factor_attribution) "
                    "VALUES (:order_id, :symbol, :pnl, :holding_secs, :entry_price, :exit_price, CAST(:market_context AS JSONB), CAST(:factor_attribution AS JSONB))"
                ),
                {
                    "order_id": order_id,
                    "symbol": symbol,
                    "pnl": pnl,
                    "holding_secs": holding_secs,
                    "entry_price": entry_price,
                    "exit_price": fill_price,
                    "market_context": json.dumps(market_context, default=str),
                    "factor_attribution": json.dumps(factor_attribution, default=str),
                },
            )

            await self._update_strategy_metrics(session, strategy_id)
            await self._update_vector_memory_outcome(
                session,
                trace_id=trace_id,
                pnl=pnl,
                holding_secs=holding_secs,
                factor_attribution=factor_attribution,
            )
            await session.commit()

        reflection_count = int(await self.redis.incr("reflection:trade_count"))
        learning_event = {
            "type": "learning_event",
            "event": "trade_evaluated",
            "order_id": order_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "pnl": pnl,
            "holding_secs": holding_secs,
            "factor_attribution": factor_attribution,
            "reflection_trade_count": reflection_count,
            "trace_id": trace_id,
        }
        await self.bus.publish("learning_events", learning_event)

    async def _fetch_prior_trade(
        self, session, strategy_id: str, symbol: str, order_id: str
    ) -> dict[str, Any] | None:
        result = await session.execute(
            text(
                "SELECT o.side, o.qty, o.price, o.filled_at, tp.exit_price, tp.created_at "
                "FROM orders o "
                "LEFT JOIN trade_performance tp ON tp.order_id = o.id "
                "WHERE o.strategy_id = :strategy_id AND o.symbol = :symbol AND o.id != :order_id AND o.status = 'filled' "
                "ORDER BY COALESCE(o.filled_at, o.created_at) DESC LIMIT 1"
            ),
            {"strategy_id": strategy_id, "symbol": symbol, "order_id": order_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def _fetch_signal_payload(
        self, session, trace_id: str | None, strategy_id: str, symbol: str
    ) -> dict[str, Any]:
        if trace_id:
            result = await session.execute(
                text(
                    "SELECT signal_data FROM agent_runs WHERE trace_id = :trace_id ORDER BY created_at DESC LIMIT 1"
                ),
                {"trace_id": trace_id},
            )
            row = result.first()
            if row is not None:
                return self._json_value(row[0])

        fallback = await session.execute(
            text(
                "SELECT signal_data FROM agent_runs WHERE strategy_id = :strategy_id AND symbol = :symbol ORDER BY created_at DESC LIMIT 1"
            ),
            {"strategy_id": strategy_id, "symbol": symbol},
        )
        row = fallback.first()
        return self._json_value(row[0]) if row is not None else {}

    def _build_factor_attribution(
        self, signal_payload: dict[str, Any]
    ) -> dict[str, float]:
        context = (
            signal_payload.get("context") if isinstance(signal_payload, dict) else {}
        )
        context = context if isinstance(context, dict) else {}
        attribution: dict[str, float] = {}
        for key in FACTOR_KEYS:
            raw = context.get(key, signal_payload.get(key, 0.0))
            try:
                attribution[key] = round(float(raw or 0.0), 6)
            except (TypeError, ValueError):
                attribution[key] = 0.0
        return attribution

    def _compute_trade_metrics(
        self,
        *,
        prior_trade: dict[str, Any] | None,
        side: str,
        qty: float,
        fill_price: float,
        filled_at: datetime,
    ) -> tuple[float, int, float]:
        if not prior_trade:
            return 0.0, 0, fill_price

        entry_price = float(
            prior_trade.get("exit_price") or prior_trade.get("price") or fill_price
        )
        prior_side = str(prior_trade.get("side", "buy")).lower()
        prior_qty = float(prior_trade.get("qty", qty) or qty)
        trade_qty = max(qty, min(qty or prior_qty, prior_qty))

        if side in {"sell", "short"} and prior_side in {"buy", "long"}:
            pnl = (fill_price - entry_price) * trade_qty
        elif side in {"buy", "long"} and prior_side in {"sell", "short"}:
            pnl = (entry_price - fill_price) * trade_qty
        else:
            return 0.0, 0, entry_price

        prior_time = self._parse_timestamp(
            prior_trade.get("filled_at") or prior_trade.get("created_at")
        )
        holding_secs = max(int((filled_at - prior_time).total_seconds()), 0)
        return round(pnl, 8), holding_secs, entry_price

    async def _update_strategy_metrics(self, session, strategy_id: str) -> None:
        result = await session.execute(
            text(
                "SELECT tp.pnl FROM trade_performance tp "
                "JOIN orders o ON o.id = tp.order_id "
                "WHERE o.strategy_id = :strategy_id ORDER BY tp.created_at ASC"
            ),
            {"strategy_id": strategy_id},
        )
        pnls = [float(row[0]) for row in result.all()]
        if not pnls:
            return

        win_rate = sum(1 for pnl in pnls if pnl > 0) / len(pnls)
        avg_pnl = mean(pnls)
        volatility = pstdev(pnls) if len(pnls) > 1 else 0.0
        sharpe = (
            0.0 if volatility == 0 else (avg_pnl / volatility) * math.sqrt(len(pnls))
        )
        running = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for pnl in pnls:
            running += pnl
            peak = max(peak, running)
            max_drawdown = min(max_drawdown, running - peak)

        existing = await session.execute(
            text("SELECT id FROM strategy_metrics WHERE strategy_id = :strategy_id"),
            {"strategy_id": strategy_id},
        )
        row = existing.mappings().first()
        params = {
            "strategy_id": strategy_id,
            "win_rate": round(win_rate, 6),
            "avg_pnl": round(avg_pnl, 8),
            "sharpe": round(sharpe, 8),
            "max_drawdown": round(abs(max_drawdown), 8),
        }
        if row is None:
            await session.execute(
                text(
                    "INSERT INTO strategy_metrics (strategy_id, win_rate, avg_pnl, sharpe, max_drawdown, updated_at) "
                    "VALUES (:strategy_id, :win_rate, :avg_pnl, :sharpe, :max_drawdown, NOW())"
                ),
                params,
            )
        else:
            await session.execute(
                text(
                    "UPDATE strategy_metrics SET win_rate = :win_rate, avg_pnl = :avg_pnl, sharpe = :sharpe, "
                    "max_drawdown = :max_drawdown, updated_at = NOW() WHERE strategy_id = :strategy_id"
                ),
                params,
            )

    async def _update_vector_memory_outcome(
        self,
        session,
        *,
        trace_id: str | None,
        pnl: float,
        holding_secs: int,
        factor_attribution: dict[str, float],
    ) -> None:
        if not trace_id:
            return
        result = await session.execute(
            text(
                "SELECT id FROM vector_memory WHERE metadata_->>'trace_id' = :trace_id ORDER BY created_at DESC LIMIT 1"
            ),
            {"trace_id": trace_id},
        )
        row = result.mappings().first()
        if row is None:
            return
        outcome = {
            "pnl": pnl,
            "holding_secs": holding_secs,
            "win": pnl > 0,
            "factor_attribution": factor_attribution,
        }
        await session.execute(
            text(
                "UPDATE vector_memory SET outcome = CAST(:outcome AS JSONB) WHERE id = :id"
            ),
            {"id": row["id"], "outcome": json.dumps(outcome, default=str)},
        )

    def _parse_timestamp(self, value: Any) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _json_value(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                log_structured("warning", "Invalid JSON payload in trade evaluator")
        return {}
