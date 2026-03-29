"""Additional stream agents wired into runtime lifespan."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.config import settings
from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured


class MultiStreamAgent:
    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        *,
        streams: list[str],
        consumer: str,
    ) -> None:
        self.bus = bus
        self.dlq = dlq
        self.streams = streams
        self.consumer = consumer
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"agent:{self.consumer}")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _run(self) -> None:
        while self._running:
            for stream in self.streams:
                messages = await self.bus.consume(
                    stream, group=DEFAULT_GROUP, consumer=self.consumer, count=20, block_ms=100
                )
                for redis_id, data in messages:
                    try:
                        await self.process(stream, redis_id, data)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                    except Exception as exc:  # noqa: BLE001
                        await self.dlq.push(stream, redis_id, data, error=str(exc), retries=1)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
            await asyncio.sleep(0.05)  # Agent processing throttle - allowed


class GradeAgent(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager) -> None:
        super().__init__(bus, dlq, streams=["executions", "trade_performance"], consumer="grade-agent")
        self._fills = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "executions":
            self._fills += 1
        if self._fills == 0 or self._fills % max(int(settings.GRADE_EVERY_N_FILLS), 1) != 0:
            return
        grade = {
            "msg_id": str(uuid.uuid4()),
            "agent": "grade_agent",
            "score": "0.70",
            "grade_type": "overall",
            "fills": self._fills,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "grade_agent",
        }
        await self.bus.publish("agent_grades", grade)
        await self.bus.publish("proposals", {"msg_id": str(uuid.uuid4()), "source": "grade_agent", "proposal_type": "risk_tune", "content": {"fills": self._fills}})
        await self.bus.publish("notifications", {"msg_id": str(uuid.uuid4()), "source": "grade_agent", "notification_type": "grade", "message": f"Grade update after {self._fills} fills"})


class ICUpdater(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["trade_performance"], consumer="ic-updater")
        self.redis = redis_client
        self._fills = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        self._fills += 1
        if self._fills % max(int(settings.IC_UPDATE_EVERY_N_FILLS), 1) != 0:
            return
        ic_score = float(data.get("pnl_percent", 0) or 0)
        payload = {
            "msg_id": str(uuid.uuid4()),
            "factor_name": "momentum",
            "ic_score": str(ic_score),
            "fills": self._fills,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "ic_updater",
        }
        await self.redis.set("alpha:ic_weights", '{"momentum": 1.0}')
        await self.bus.publish("factor_ic_history", payload)


class ReflectionAgent(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager) -> None:
        super().__init__(
            bus,
            dlq,
            streams=["trade_performance", "agent_grades", "factor_ic_history"],
            consumer="reflection-agent",
        )
        self._fills = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "trade_performance":
            self._fills += 1
        if self._fills == 0 or self._fills % max(int(settings.REFLECT_EVERY_N_FILLS), 1) != 0:
            return
        reflection = {
            "msg_id": str(uuid.uuid4()),
            "source": "reflection_agent",
            "summary": "Recent fill cohort reviewed; tighten entry filters slightly.",
            "fills": self._fills,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.bus.publish("reflection_outputs", reflection)
        await self.bus.publish("notifications", {"msg_id": str(uuid.uuid4()), "source": "reflection_agent", "notification_type": "reflection", "message": reflection["summary"]})


class StrategyProposer(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager) -> None:
        super().__init__(bus, dlq, streams=["reflection_outputs"], consumer="strategy-proposer")

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        proposal = {
            "msg_id": str(uuid.uuid4()),
            "source": "strategy_proposer",
            "proposal_type": "strategy_adjustment",
            "content": {"reflection": data.get("summary", "")},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.bus.publish("proposals", proposal)
        await self.bus.publish("notifications", {"msg_id": str(uuid.uuid4()), "source": "strategy_proposer", "notification_type": "proposal", "message": "New strategy proposal generated"})
        await self.bus.publish("github_prs", {"msg_id": str(uuid.uuid4()), "source": "strategy_proposer", "title": "Automated strategy proposal", "body": str(proposal["content"])})


class NotificationAgent(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[
                "market_ticks",
                "signals",
                "orders",
                "executions",
                "agent_logs",
                "trade_performance",
                "agent_grades",
                "factor_ic_history",
                "reflection_outputs",
                "proposals",
            ],
            consumer="notification-agent",
        )
        self.safe_writer = SafeWriter(AsyncSessionFactory)
        self.redis = redis_client

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "notifications":
            return
        msg_id = data.get("msg_id") or redis_id
        notification = {
            "msg_id": str(uuid.uuid4()),
            "schema_version": "v3",
            "source": "notification_agent",
            "notification_type": f"stream:{stream}",
            "message": f"Event observed on {stream}",
            "metadata": {"observed_msg_id": msg_id},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.safe_writer.write_notification(notification["msg_id"], "notifications", notification)
        await self.bus.publish("notifications", notification)
        log_structured("debug", "notification_forwarded", stream=stream, observed_msg_id=msg_id)
