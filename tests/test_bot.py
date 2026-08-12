"""Unit tests for the core, deterministic pieces (no network required)."""
import numpy as np
import pandas as pd

from app import indicators as ind
from app.config import RiskConfig, StrategyConfig
from app.models import Side
from app.portfolio import PaperPortfolio
from app.risk import RiskManager
from app.strategy import Strategy


def _synthetic(n=400, trend=0.0, seed=1):
    """Build an OHLCV frame with a controllable drift."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(trend, 1.0, n).cumsum()
    close = 100 + steps
    close = np.maximum(close, 1.0)
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    open_ = close + rng.normal(0, 0.3, n)
    vol = rng.uniform(10, 100, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


# --- Indicators -------------------------------------------------------------

def test_rsi_bounds():
    df = _synthetic()
    r = ind.rsi(df["close"], 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_atr_positive():
    df = _synthetic()
    a = ind.atr(df["high"], df["low"], df["close"], 14).dropna()
    assert (a >= 0).all()


def test_adx_range():
    df = _synthetic(trend=0.2)
    a = ind.adx(df["high"], df["low"], df["close"], 14).dropna()
    assert (a >= 0).all() and (a <= 100).all()


def test_ema_tracks_price():
    df = _synthetic(trend=0.3)
    e = ind.ema(df["close"], 20)
    # In a persistent uptrend a shorter EMA should end above the start.
    assert e.iloc[-1] > e.iloc[20]


# --- Strategy ---------------------------------------------------------------

def test_strategy_holds_without_history():
    strat = Strategy(StrategyConfig())
    df = _synthetic(n=10)
    sig = strat.generate("BTC/USDT", df)
    assert sig.action.value == "hold"


def test_strategy_uptrend_leans_bullish():
    strat = Strategy(StrategyConfig())
    df = _synthetic(trend=0.4, seed=7)
    sig = strat.generate("BTC/USDT", df)
    # Strong uptrend should not produce a SELL.
    assert sig.action.value in ("buy", "hold")
    assert 0.0 <= sig.score <= 1.0


# --- Risk management --------------------------------------------------------

def test_position_sizing_respects_risk():
    rm = RiskManager(RiskConfig(risk_per_trade=0.01, atr_stop_multiplier=2.0))
    order = rm.size_position(Side.LONG, equity=10000, entry_price=100, atr_value=2.0)
    assert order is not None
    # Loss at stop should be ~1% of equity (100).
    loss_at_stop = (order.entry_price - order.stop_loss) * order.quantity
    assert abs(loss_at_stop - 100) < 1e-6


def test_reward_risk_ratio_applied():
    rm = RiskManager(RiskConfig(reward_risk_ratio=2.0, atr_stop_multiplier=2.0))
    order = rm.size_position(Side.LONG, 10000, 100, 2.0)
    risk = order.entry_price - order.stop_loss
    reward = order.take_profit - order.entry_price
    assert abs(reward - 2 * risk) < 1e-6


def test_drawdown_circuit_breaker():
    rm = RiskManager(RiskConfig(max_drawdown_halt=0.15))
    rm.update_equity(10000)
    assert not rm.trading_halted(9000)   # 10% dd -> ok
    assert rm.trading_halted(8000)       # 20% dd -> halt


def test_stop_loss_exit_triggers():
    rm = RiskManager(RiskConfig())
    order = rm.size_position(Side.LONG, 10000, 100, 2.0)
    from app.models import Position
    pos = Position("BTC/USDT", Side.LONG, order.entry_price, order.quantity,
                   order.stop_loss, order.take_profit)
    assert rm.check_exit(pos, order.stop_loss - 1) == "stop_loss"


# --- Portfolio --------------------------------------------------------------

def test_portfolio_open_close_pnl():
    pf = PaperPortfolio(10000)
    pf.open("BTC/USDT", Side.LONG, 100, 1.0, 95, 110)
    assert "BTC/USDT" in pf.positions
    trade = pf.close("BTC/USDT", 110, "take_profit")
    assert trade is not None
    assert trade.pnl > 0                 # profitable round trip
    assert "BTC/USDT" not in pf.positions


def test_portfolio_rejects_unaffordable_order():
    pf = PaperPortfolio(100)
    pos = pf.open("BTC/USDT", Side.LONG, 100, 100, 95, 110)  # needs ~10000
    assert pos is None
