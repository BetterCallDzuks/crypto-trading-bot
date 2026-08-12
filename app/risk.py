"""Risk management — position sizing, stops/targets, and the circuit breaker.

This module is intentionally boring and conservative. In algorithmic trading
survival matters far more than any single winning trade: a strategy that never
blows up compounds; one that risks ruin eventually hits it.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import RiskConfig
from .models import Position, Side


@dataclass
class SizedOrder:
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self._peak_equity: float = 0.0

    # --- Drawdown circuit breaker ------------------------------------------
    def update_equity(self, equity: float) -> None:
        self._peak_equity = max(self._peak_equity, equity)

    def current_drawdown(self, equity: float) -> float:
        if self._peak_equity <= 0:
            return 0.0
        return max(0.0, (self._peak_equity - equity) / self._peak_equity)

    def trading_halted(self, equity: float) -> bool:
        """True once drawdown from the equity peak breaches the halt threshold."""
        return self.current_drawdown(equity) >= self.cfg.max_drawdown_halt

    # --- Position sizing ----------------------------------------------------
    def size_position(
        self,
        side: Side,
        equity: float,
        entry_price: float,
        atr_value: float,
    ) -> SizedOrder | None:
        """Fixed-fractional sizing off an ATR-based stop.

        risk_amount = equity * risk_per_trade
        stop distance = atr_stop_multiplier * ATR
        quantity = risk_amount / stop_distance
        so that hitting the stop loses ~risk_per_trade of the account.
        """
        if atr_value <= 0 or entry_price <= 0 or equity <= 0:
            return None

        stop_distance = self.cfg.atr_stop_multiplier * atr_value
        if stop_distance <= 0:
            return None

        risk_amount = equity * self.cfg.risk_per_trade
        quantity = risk_amount / stop_distance
        if quantity <= 0:
            return None

        target_distance = stop_distance * self.cfg.reward_risk_ratio
        if side == Side.LONG:
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + target_distance
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - target_distance

        # Never let a single position's notional exceed available equity
        # (with leverage headroom for perpetuals).
        max_notional = equity * max(1, self.cfg.leverage)
        if quantity * entry_price > max_notional:
            quantity = max_notional / entry_price

        return SizedOrder(quantity, entry_price, stop_loss, take_profit)

    # --- Exit checks --------------------------------------------------------
    def check_exit(self, pos: Position, price: float) -> str | None:
        """Return an exit reason if a stop/target/trailing-stop is hit."""
        if pos.side == Side.LONG:
            pos.highest_price = max(pos.highest_price, price)
            trail = pos.highest_price - self.cfg.trailing_atr_multiplier * self._atr_from_stop(pos)
            if price <= pos.stop_loss:
                return "stop_loss"
            if price >= pos.take_profit:
                return "take_profit"
            if trail > pos.stop_loss and price <= trail:
                return "trailing_stop"
        else:
            pos.lowest_price = min(pos.lowest_price, price)
            trail = pos.lowest_price + self.cfg.trailing_atr_multiplier * self._atr_from_stop(pos)
            if price >= pos.stop_loss:
                return "stop_loss"
            if price <= pos.take_profit:
                return "take_profit"
            if trail < pos.stop_loss and price >= trail:
                return "trailing_stop"
        return None

    def _atr_from_stop(self, pos: Position) -> float:
        """Recover the ATR used at entry from the stop distance."""
        dist = abs(pos.entry_price - pos.stop_loss)
        return dist / self.cfg.atr_stop_multiplier if self.cfg.atr_stop_multiplier else 0.0
