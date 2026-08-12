"""SQLite persistence for the trade ledger and equity curve.

Lightweight, single-file, zero-config — fits the "minimum maintenance" goal.
Survives restarts so the dashboard shows real history, not just this session.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .models import Trade, Side

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.db"


class Database:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, side TEXT,
                entry_price REAL, exit_price REAL, quantity REAL,
                pnl REAL, pnl_pct REAL, reason TEXT,
                opened_at REAL, closed_at REAL
            );
            CREATE TABLE IF NOT EXISTS equity_curve (
                ts REAL PRIMARY KEY,
                equity REAL
            );
            """
        )
        self.conn.commit()

    def record_trade(self, t: Trade) -> None:
        self.conn.execute(
            """INSERT INTO trades
               (symbol, side, entry_price, exit_price, quantity, pnl, pnl_pct,
                reason, opened_at, closed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (t.symbol, t.side.value, t.entry_price, t.exit_price, t.quantity,
             t.pnl, t.pnl_pct, t.reason, t.opened_at, t.closed_at),
        )
        self.conn.commit()

    def record_equity(self, equity: float, ts: float | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO equity_curve (ts, equity) VALUES (?, ?)",
            (ts or time.time(), equity),
        )
        self.conn.commit()

    def recent_trades(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def equity_history(self, limit: int = 1000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ts, equity FROM equity_curve ORDER BY ts ASC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def load_trades(self) -> list[Trade]:
        out = []
        for r in self.recent_trades(limit=10000):
            out.append(Trade(
                symbol=r["symbol"], side=Side(r["side"]),
                entry_price=r["entry_price"], exit_price=r["exit_price"],
                quantity=r["quantity"], pnl=r["pnl"], pnl_pct=r["pnl_pct"],
                reason=r["reason"], opened_at=r["opened_at"], closed_at=r["closed_at"],
            ))
        return out
