#!/usr/bin/env python3
"""Read-only live-regime diagnostic for the trading system.

Answers the two empirical questions a static code audit cannot:

  1. Is the ReasoningAgent's advisory output BUY- or SELL-skewed?
     -> tallies the action distribution in Redis ``decisions:recent``.
  2. Are those SELLs even executable?
     -> reads the PaperBroker positions (``paper:positions:*`` — the execution
        source of truth) and counts how many SELL decisions target a symbol
        with NO open long. That "phantom SELL" count is the empirical measure
        of the advisory-vs-execution disconnect described in the audit.

This script ONLY reads Redis. It never writes, trades, or mutates state, and it
cannot see the in-process InMemoryStore order ledger (that lives inside the
running app, not Redis) — for the ledger view use the app's ``/dashboard/state``
endpoint. Gate-clearance rates for BUYs are not in Redis either; they appear
only in the ``execution_gated_*`` structured logs.

Usage:
    REDIS_URL=redis://host:port python scripts/diagnose_live_regime.py [--limit 500]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from typing import Any

from api.constants import FieldName, PositionSide
from api.redis_client import close_redis, get_redis
from api.services.redis_store import RedisStore


async def _scan_paper_positions(redis: Any) -> dict[str, dict[str, Any]]:
    """SCAN every ``paper:positions:*`` key and return {symbol: position}."""
    positions: dict[str, dict[str, Any]] = {}
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="paper:positions:*", count=100)
        for key in keys:
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                continue
            symbol = parsed.get(FieldName.SYMBOL) or key.rsplit(":", 1)[-1]
            positions[str(symbol)] = parsed
        if cursor == 0:
            break
    return positions


def _is_open_long(position: dict[str, Any] | None) -> bool:
    """True when the broker holds an open LONG (the only state a SELL can close)."""
    if not isinstance(position, dict):
        return False
    side = str(position.get(FieldName.SIDE) or "").lower()
    try:
        qty = float(position.get(FieldName.QTY) or 0.0)
    except (TypeError, ValueError):
        qty = 0.0
    return side == PositionSide.LONG and qty > 0


def _print_action_distribution(decisions: list[dict[str, Any]], stats: dict[str, Any]) -> None:
    actions = Counter(str(d.get(FieldName.ACTION, "")).lower() or "(blank)" for d in decisions)
    total = sum(actions.values())
    print("=" * 64)
    print(f"DECISION ACTION DISTRIBUTION (last {len(decisions)} in decisions:recent)")
    print("=" * 64)
    if not decisions:
        print("  (decisions:recent is empty — no reasoning output recorded yet)")
    for action, count in actions.most_common():
        pct = (count / total * 100) if total else 0.0
        print(f"  {action:<10} {count:>5}  ({pct:5.1f}%)")
    last_hour = stats.get(FieldName.LAST_HOUR, {})
    print(
        f"\n  last hour: buys={last_hour.get(FieldName.BUYS, 0)} "
        f"sells={last_hour.get(FieldName.SELLS, 0)} holds={last_hour.get(FieldName.HOLDS, 0)}"
    )


def _print_positions(positions: dict[str, dict[str, Any]]) -> None:
    print("\n" + "=" * 64)
    print("PAPER BROKER POSITIONS (paper:positions:* — execution source of truth)")
    print("=" * 64)
    if not positions:
        print("  (none — the broker is flat on every symbol)")
        return
    for symbol, p in sorted(positions.items()):
        print(
            f"  {symbol:<10} side={p.get(FieldName.SIDE)} "
            f"qty={p.get(FieldName.QTY)} entry={p.get(FieldName.ENTRY_PRICE)}"
        )


def _print_phantom_sells(
    decisions: list[dict[str, Any]], positions: dict[str, dict[str, Any]]
) -> None:
    sell_decisions = [d for d in decisions if str(d.get(FieldName.ACTION, "")).lower() == "sell"]
    phantom = [
        d
        for d in sell_decisions
        if not _is_open_long(positions.get(str(d.get(FieldName.SYMBOL) or "")))
    ]
    n_sell = len(sell_decisions)
    n_phantom = len(phantom)
    pct = (n_phantom / n_sell * 100) if n_sell else 0.0
    print("\n" + "=" * 64)
    print("PHANTOM SELLS (advisory SELL for a symbol with no open long)")
    print("=" * 64)
    print(f"  {n_phantom}/{n_sell} SELL decisions ({pct:.1f}%) target a symbol the broker does")
    print("  NOT hold. These are advertised in the feed and then rejected by the")
    print("  ExecutionEngine, so they never produce a fill or PnL.")
    print("\nNOTE: BUY gate-clearance % is not in Redis — see `execution_gated_*` logs.")


async def main(limit: int) -> None:
    redis = await get_redis()
    store = RedisStore(redis)
    try:
        decisions = await store.list_decisions(limit=limit)
        stats = await store.decision_stats()
        positions = await _scan_paper_positions(redis)
    finally:
        await close_redis()

    _print_action_distribution(decisions, stats)
    _print_positions(positions)
    _print_phantom_sells(decisions, positions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only live-regime diagnostic (Redis only).")
    parser.add_argument(
        "--limit", type=int, default=500, help="size of the decisions:recent window to scan"
    )
    args = parser.parse_args()
    asyncio.run(main(args.limit))
