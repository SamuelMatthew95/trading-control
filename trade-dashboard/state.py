import json
import os
from datetime import datetime
from dataclasses import dataclass, asdict

TRADE_LOG_PATH = "assets/trade-log.json"

@dataclass
class Trade:
    date: str
    asset: str
    direction: str
    size: float
    entry: float
    stop: float
    target: float
    rr_ratio: float
    exit: float = None
    pnl: float = None
    outcome: str = "OPEN"

def load_trades() -> list[dict]:
    if not os.path.exists(TRADE_LOG_PATH):
        return []
    with open(TRADE_LOG_PATH) as f:
        return json.load(f)

def save_trade(trade: Trade):
    trades = load_trades()
    trades.append(asdict(trade))
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(trades, f, indent=2)

def get_win_rate(trades: list[dict]) -> float:
    closed = [t for t in trades if t["outcome"] != "OPEN"]
    if not closed:
        return 0.0
    wins = [t for t in closed if t["pnl"] > 0]
    return len(wins) / len(closed)

def get_total_pnl(trades: list[dict]) -> float:
    return sum(t.get("pnl", 0) or 0 for t in trades)

def update_trade_outcome(trade_index: int, exit_price: float):
    """Update a trade with exit information"""
    trades = load_trades()
    if 0 <= trade_index < len(trades):
        trade = trades[trade_index]
        trade["exit"] = exit_price
        trade["pnl"] = (exit_price - trade["entry"]) * trade["size"]
        trade["outcome"] = "CLOSED"
        
        with open(TRADE_LOG_PATH, "w") as f:
            json.dump(trades, f, indent=2)
        return True
    return False
