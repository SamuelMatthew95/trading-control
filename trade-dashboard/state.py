import sqlite3
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional

DATABASE_PATH = "assets/trades.db"

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
    exit: Optional[float] = None
    pnl: Optional[float] = None
    outcome: str = "OPEN"

def init_database():
    """Initialize the SQLite database with trades table"""
    os.makedirs("assets", exist_ok=True)
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            asset TEXT NOT NULL,
            direction TEXT NOT NULL,
            size REAL NOT NULL,
            entry REAL NOT NULL,
            stop REAL NOT NULL,
            target REAL NOT NULL,
            rr_ratio REAL NOT NULL,
            exit_price REAL,
            pnl REAL,
            outcome TEXT DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

def load_trades() -> List[dict]:
    """Load all trades from database"""
    if not os.path.exists(DATABASE_PATH):
        init_database()
        return []
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT date, asset, direction, size, entry, stop, target, rr_ratio, 
               exit_price, pnl, outcome
        FROM trades 
        ORDER BY date DESC
    """)
    
    trades = []
    for row in cursor.fetchall():
        trades.append({
            "date": row[0],
            "asset": row[1], 
            "direction": row[2],
            "size": row[3],
            "entry": row[4],
            "stop": row[5],
            "target": row[6],
            "rr_ratio": row[7],
            "exit": row[8],
            "pnl": row[9],
            "outcome": row[10]
        })
    
    conn.close()
    return trades

def save_trade(trade: Trade) -> int:
    """Save a trade to database and return its ID"""
    init_database()
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO trades (date, asset, direction, size, entry, stop, target, rr_ratio, exit_price, pnl, outcome)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.date, trade.asset, trade.direction, trade.size,
        trade.entry, trade.stop, trade.target, trade.rr_ratio,
        trade.exit, trade.pnl, trade.outcome
    ))
    
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return trade_id

def get_win_rate(trades: List[dict]) -> float:
    """Calculate win rate from trades"""
    closed = [t for t in trades if t["outcome"] != "OPEN"]
    if not closed:
        return 0.0
    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    return len(wins) / len(closed)

def get_total_pnl(trades: List[dict]) -> float:
    """Calculate total P&L from trades"""
    return sum(t.get("pnl", 0) or 0 for t in trades)

def update_trade_outcome(trade_id: int, exit_price: float):
    """Update a trade with exit information by ID"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Get trade details first
    cursor.execute("SELECT entry, size, direction FROM trades WHERE id = ?", (trade_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return False
    
    entry, size, direction = result
    
    # Calculate P&L
    if direction.upper() == "LONG":
        pnl = (exit_price - entry) * size
    else:  # SHORT
        pnl = (entry - exit_price) * size
    
    # Determine outcome
    if pnl > 0:
        outcome = "WIN"
    elif pnl < 0:
        outcome = "LOSS"
    else:
        outcome = "BREAKEVEN"
    
    # Update trade
    cursor.execute("""
        UPDATE trades 
        SET exit_price = ?, pnl = ?, outcome = 'CLOSED', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (exit_price, pnl, trade_id))
    
    conn.commit()
    conn.close()
    return True

def get_open_trades() -> List[dict]:
    """Get all open trades"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, date, asset, direction, size, entry, stop, target, rr_ratio
        FROM trades 
        WHERE outcome = 'OPEN'
        ORDER BY date DESC
    """)
    
    trades = []
    for row in cursor.fetchall():
        trades.append({
            "id": row[0],
            "date": row[1],
            "asset": row[2],
            "direction": row[3],
            "size": row[4],
            "entry": row[5],
            "stop": row[6],
            "target": row[7],
            "rr_ratio": row[8]
        })
    
    conn.close()
    return trades

def get_trade_statistics() -> dict:
    """Get comprehensive trade statistics"""
    trades = load_trades()
    closed_trades = [t for t in trades if t["outcome"] != "OPEN"]
    
    if not closed_trades:
        return {
            "total_trades": len(trades),
            "open_trades": len(trades),
            "closed_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0
        }
    
    wins = [t for t in closed_trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed_trades if (t.get("pnl") or 0) < 0]
    
    total_pnl = sum(t.get("pnl", 0) or 0 for t in closed_trades)
    avg_win = sum(t.get("pnl", 0) or 0 for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("pnl", 0) or 0 for t in losses) / len(losses) if losses else 0
    
    gross_profit = sum(t.get("pnl", 0) or 0 for t in wins)
    gross_loss = abs(sum(t.get("pnl", 0) or 0 for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    return {
        "total_trades": len(trades),
        "open_trades": len(trades) - len(closed_trades),
        "closed_trades": len(closed_trades),
        "win_rate": len(wins) / len(closed_trades),
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor
    }
