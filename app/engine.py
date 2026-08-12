"""The trading engine — the loop that turns signals into (paper or live) trades.

Runs in a background thread so the web dashboard stays responsive and can
start/stop it. Every cycle it:
  1. pulls fresh candles for each symbol
  2. checks open positions for stop/target/trailing exits
  3. asks the strategy for a signal
  4. sizes and opens new positions within risk limits
  5. updates equity, the circuit breaker, and persistence
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from . import indicators as ind
from .config import BotConfig, Settings
from .database import Database
from .exchange import ExchangeClient
from .models import Side, SignalAction
from .portfolio import PaperPortfolio
from .risk import RiskManager
from .strategy import Strategy

log = logging.getLogger("engine")


@dataclass
class EngineState:
    running: bool = False
    halted: bool = False
    last_cycle: float = 0.0
    last_error: str = ""
    prices: dict[str, float] = field(default_factory=dict)
    signals: dict[str, dict] = field(default_factory=dict)


class TradingEngine:
    def __init__(self, settings: Settings, config: BotConfig, db: Database | None = None):
        self.settings = settings
        self.config = config
        self.db = db or Database()
        self.exchange = ExchangeClient(settings)
        self.strategy = Strategy(config.strategy)
        self.risk = RiskManager(config.risk)
        self.portfolio = PaperPortfolio(config.paper_starting_balance)
        # Rehydrate ledger so restarts keep history visible.
        self.portfolio.trades = self.db.load_trades()

        self.state = EngineState()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # --- Lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self.state.running:
            return
        self._stop.clear()
        self.state.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="engine")
        self._thread.start()
        log.info("Engine started (mode=%s)", self.settings.trading_mode)

    def stop(self) -> None:
        self._stop.set()
        self.state.running = False
        log.info("Engine stop requested")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._cycle()
                self.state.last_error = ""
            except Exception as exc:  # keep the loop alive; surface on dashboard
                self.state.last_error = str(exc)
                log.exception("Cycle error: %s", exc)
            self._stop.wait(self.config.poll_interval_seconds)
        self.state.running = False

    # --- One evaluation cycle ----------------------------------------------
    def _cycle(self) -> None:
        prices: dict[str, float] = {}

        for symbol in self.config.symbols:
            df = self.exchange.fetch_ohlcv(symbol, self.config.timeframe, limit=500)
            if df.empty:
                continue
            price = float(df["close"].iloc[-1])
            prices[symbol] = price

            atr_series = ind.atr(df["high"], df["low"], df["close"], self.config.risk.atr_period)
            atr_value = float(atr_series.iloc[-1])

            # 1) Manage existing position for this symbol first.
            self._manage_position(symbol, price)

            # 2) Look for a new entry.
            signal = self.strategy.generate(symbol, df)
            self.state.signals[symbol] = signal.to_dict()
            self._maybe_enter(symbol, signal, price, atr_value, prices)

        self.state.prices = prices

        equity = self.portfolio.equity(prices)
        self.risk.update_equity(equity)
        self.state.halted = self.risk.trading_halted(equity)
        self.db.record_equity(equity)
        self.state.last_cycle = time.time()

    def _manage_position(self, symbol: str, price: float) -> None:
        pos = self.portfolio.positions.get(symbol)
        if pos is None:
            return
        reason = self.risk.check_exit(pos, price)
        if reason:
            trade = self.portfolio.close(symbol, price, reason)
            if trade:
                self.db.record_trade(trade)
                self._execute_live(symbol, _flip(pos.side), pos.quantity)
                log.info("Closed %s (%s) pnl=%.2f", symbol, reason, trade.pnl)

    def _maybe_enter(self, symbol, signal, price, atr_value, prices) -> None:
        if signal.action == SignalAction.HOLD:
            return
        if symbol in self.portfolio.positions:
            return
        equity = self.portfolio.equity(prices)
        if self.risk.trading_halted(equity):
            return
        if len(self.portfolio.positions) >= self.config.risk.max_open_positions:
            return
        # Spot markets can't be shorted here — long-only for spot.
        side = Side.LONG if signal.action == SignalAction.BUY else Side.SHORT
        if self.settings.market_type == "spot" and side == Side.SHORT:
            return

        order = self.risk.size_position(side, equity, price, atr_value)
        if order is None:
            return
        pos = self.portfolio.open(symbol, side, order.entry_price, order.quantity,
                                  order.stop_loss, order.take_profit)
        if pos:
            self._execute_live(symbol, side, order.quantity)
            log.info("Opened %s %s qty=%.6f @ %.2f (score=%.2f)",
                     side.value, symbol, order.quantity, price, signal.score)

    def _execute_live(self, symbol: str, side: Side, quantity: float) -> None:
        """Mirror a paper action onto the real exchange when live-confirmed."""
        if not self.settings.live_confirmed:
            return
        try:
            self.exchange.create_market_order(symbol, side, quantity)
        except Exception as exc:
            self.state.last_error = f"live order failed: {exc}"
            log.error("Live order failed for %s: %s", symbol, exc)

    # --- Dashboard snapshot -------------------------------------------------
    def snapshot(self) -> dict:
        prices = self.state.prices
        stats = self.portfolio.stats(prices)
        equity = stats["equity"]
        return {
            "mode": self.settings.trading_mode,
            "live_confirmed": self.settings.live_confirmed,
            "exchange": self.settings.exchange_id,
            "market_type": self.settings.market_type,
            "running": self.state.running,
            "halted": self.state.halted,
            "drawdown_pct": self.risk.current_drawdown(equity) * 100,
            "last_cycle": self.state.last_cycle,
            "last_error": self.state.last_error,
            "stats": stats,
            "positions": [
                {**p.to_dict(),
                 "current_price": prices.get(sym, p.entry_price),
                 "unrealized_pnl": p.unrealized_pnl(prices.get(sym, p.entry_price)),
                 "unrealized_pnl_pct": p.unrealized_pnl_pct(prices.get(sym, p.entry_price))}
                for sym, p in self.portfolio.positions.items()
            ],
            "signals": self.state.signals,
            "symbols": self.config.symbols,
        }


def _flip(side: Side) -> Side:
    return Side.SHORT if side == Side.LONG else Side.LONG
