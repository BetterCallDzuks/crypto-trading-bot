"""Core domain data structures shared across the bot."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    """A strategy's verdict for one symbol at one moment."""
    symbol: str
    action: SignalAction
    score: float                 # 0..1 confidence
    price: float
    reasons: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["action"] = self.action.value
        return d


@dataclass
class Position:
    symbol: str
    side: Side
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    opened_at: float = field(default_factory=time.time)
    highest_price: float = 0.0   # for trailing stop (long)
    lowest_price: float = 0.0    # for trailing stop (short)

    def __post_init__(self):
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price
        if self.lowest_price == 0.0:
            self.lowest_price = self.entry_price

    def unrealized_pnl(self, price: float) -> float:
        if self.side == Side.LONG:
            return (price - self.entry_price) * self.quantity
        return (self.entry_price - price) * self.quantity

    def unrealized_pnl_pct(self, price: float) -> float:
        cost = self.entry_price * self.quantity
        return (self.unrealized_pnl(price) / cost) * 100 if cost else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["side"] = self.side.value
        return d


@dataclass
class Trade:
    """A closed round-trip trade, for the ledger."""
    symbol: str
    side: Side
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    reason: str
    opened_at: float
    closed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["side"] = self.side.value
        return d
