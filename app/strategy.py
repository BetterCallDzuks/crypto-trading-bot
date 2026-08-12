"""Signal generation: a weighted ensemble of classic, well-understood signals.

Philosophy
----------
No single indicator is reliable. We combine several *independent* views of the
market and only act when a majority agree. Each component votes in [-1, +1]
(bearish..bullish); votes are weighted and summed into a score in [-1, +1].
The engine opens a long when the score clears +min_signal_score, a short when
it clears -min_signal_score, and otherwise holds.

A hard trend-strength filter (ADX) suppresses trend signals during choppy,
directionless markets — the environment where trend systems bleed money.

This is a solid, transparent baseline — NOT a magic money printer. Validate it
with the backtester before ever risking real capital.
"""
from __future__ import annotations

import pandas as pd

from . import indicators as ind
from .config import StrategyConfig
from .models import Signal, SignalAction


# Relative weight of each voter in the ensemble.
WEIGHTS = {
    "trend": 0.30,      # EMA fast vs slow
    "macd": 0.25,      # momentum
    "rsi": 0.20,      # over-extension / mean reversion
    "bbands": 0.15,      # price vs volatility envelope
    "adx_dir": 0.10,      # directional confirmation
}


class Strategy:
    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg

    def min_bars(self) -> int:
        """Bars of history needed before indicators are trustworthy."""
        return max(self.cfg.ema_slow, self.cfg.macd_slow, self.cfg.adx_period) * 3

    def generate(self, symbol: str, df: pd.DataFrame) -> Signal:
        """`df` must have columns: open, high, low, close, volume."""
        c = self.cfg
        close, high, low = df["close"], df["high"], df["low"]

        if len(df) < self.min_bars():
            return Signal(symbol, SignalAction.HOLD, 0.0, float(close.iloc[-1]),
                          ["insufficient history"])

        ema_fast = ind.ema(close, c.ema_fast)
        ema_slow = ind.ema(close, c.ema_slow)
        rsi = ind.rsi(close, c.rsi_period)
        macd_line, macd_sig, macd_hist = ind.macd(close, c.macd_fast, c.macd_slow, c.macd_signal)
        adx = ind.adx(high, low, close, c.adx_period)
        bb_up, bb_mid, bb_low = ind.bollinger_bands(close, c.bb_period, c.bb_std)

        price = float(close.iloc[-1])
        adx_now = float(adx.iloc[-1])
        trending = adx_now >= c.adx_trend_threshold

        votes: dict[str, float] = {}
        reasons: list[str] = []

        # 1) Trend: fast EMA above/below slow EMA. Muted when not trending.
        trend_raw = 1.0 if ema_fast.iloc[-1] > ema_slow.iloc[-1] else -1.0
        votes["trend"] = trend_raw * (1.0 if trending else 0.3)
        reasons.append(f"EMA{c.ema_fast}{'>' if trend_raw > 0 else '<'}EMA{c.ema_slow}")

        # 2) MACD histogram sign + slope.
        hist_now = float(macd_hist.iloc[-1])
        hist_prev = float(macd_hist.iloc[-2])
        macd_vote = 0.0
        if hist_now > 0:
            macd_vote = 1.0 if hist_now >= hist_prev else 0.5
        elif hist_now < 0:
            macd_vote = -1.0 if hist_now <= hist_prev else -0.5
        votes["macd"] = macd_vote
        reasons.append(f"MACD hist {hist_now:+.4f}")

        # 3) RSI: reward pullbacks-in-uptrend, penalise overbought extremes.
        rsi_now = float(rsi.iloc[-1])
        if rsi_now >= c.rsi_overbought:
            rsi_vote = -1.0
        elif rsi_now <= c.rsi_oversold:
            rsi_vote = 1.0
        else:
            # Centre RSI at 50 and scale gently; agrees mildly with momentum.
            rsi_vote = (rsi_now - 50.0) / 50.0
        votes["rsi"] = rsi_vote
        reasons.append(f"RSI {rsi_now:.1f}")

        # 4) Bollinger position within the envelope (mean-reversion tilt).
        upper, lower = float(bb_up.iloc[-1]), float(bb_low.iloc[-1])
        width = upper - lower
        if width > 0:
            pos = (price - lower) / width  # 0 at lower band, 1 at upper band
            # Near lower band -> bullish; near upper -> bearish.
            bb_vote = float(pd.Series([1.0 - 2.0 * pos]).clip(-1, 1).iloc[0])
        else:
            bb_vote = 0.0
        votes["bbands"] = bb_vote

        # 5) ADX directional confirmation (only counts when trending).
        votes["adx_dir"] = (trend_raw if trending else 0.0)
        reasons.append(f"ADX {adx_now:.1f}{'(trend)' if trending else '(range)'}")

        score = sum(WEIGHTS[k] * v for k, v in votes.items())
        score = max(-1.0, min(1.0, score))

        if score >= c.min_signal_score:
            action = SignalAction.BUY
        elif score <= -c.min_signal_score:
            action = SignalAction.SELL
        else:
            action = SignalAction.HOLD

        return Signal(symbol, action, abs(score), price, reasons)
