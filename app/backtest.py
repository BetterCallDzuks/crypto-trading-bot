"""Backtester — replay the exact strategy + risk logic over historical candles.

Same Strategy, RiskManager and PaperPortfolio classes the live engine uses, so
what you backtest is what you trade. Run it before trusting the bot with money:

    python -m app.backtest --symbol BTC/USDT --timeframe 1h --limit 1500
"""
from __future__ import annotations

import argparse

import pandas as pd

from . import indicators as ind
from .config import load_bot_config, load_settings
from .exchange import ExchangeClient
from .models import Side, SignalAction
from .portfolio import PaperPortfolio
from .risk import RiskManager
from .strategy import Strategy


def run_backtest(df: pd.DataFrame, symbol: str, config) -> dict:
    strategy = Strategy(config.strategy)
    risk = RiskManager(config.risk)
    pf = PaperPortfolio(config.paper_starting_balance)

    atr_series = ind.atr(df["high"], df["low"], df["close"], config.risk.atr_period)
    warmup = strategy.min_bars()
    equity_curve: list[float] = []

    for i in range(warmup, len(df)):
        window = df.iloc[: i + 1]
        price = float(window["close"].iloc[-1])
        atr_value = float(atr_series.iloc[i])
        prices = {symbol: price}

        # Manage open position.
        pos = pf.positions.get(symbol)
        if pos is not None:
            reason = risk.check_exit(pos, price)
            if reason:
                pf.close(symbol, price, reason)

        # Entry.
        if symbol not in pf.positions:
            equity = pf.equity(prices)
            if not risk.trading_halted(equity):
                sig = strategy.generate(symbol, window)
                if sig.action != SignalAction.HOLD:
                    side = Side.LONG if sig.action == SignalAction.BUY else Side.SHORT
                    order = risk.size_position(side, equity, price, atr_value)
                    if order:
                        pf.open(symbol, side, order.entry_price, order.quantity,
                                order.stop_loss, order.take_profit)

        equity = pf.equity(prices)
        risk.update_equity(equity)
        equity_curve.append(equity)

    # Close any residual position at the last price.
    last_price = float(df["close"].iloc[-1])
    if symbol in pf.positions:
        pf.close(symbol, last_price, "backtest_end")

    stats = pf.stats({symbol: last_price})
    peak = config.paper_starting_balance
    max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak if peak else 0.0)
    stats["max_drawdown_pct"] = max_dd * 100
    stats["bars_tested"] = len(equity_curve)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest the trading strategy.")
    ap.add_argument("--symbol", default=None, help="e.g. BTC/USDT (default: all configured)")
    ap.add_argument("--timeframe", default=None)
    ap.add_argument("--limit", type=int, default=1500, help="number of candles")
    args = ap.parse_args()

    settings = load_settings()
    config = load_bot_config()
    timeframe = args.timeframe or config.timeframe
    symbols = [args.symbol] if args.symbol else config.symbols

    exchange = ExchangeClient(settings)
    print(f"\nBacktest — exchange={settings.exchange_id} timeframe={timeframe} "
          f"limit={args.limit}\n" + "=" * 62)

    for symbol in symbols:
        df = exchange.fetch_ohlcv(symbol, timeframe, limit=args.limit)
        if df.empty:
            print(f"{symbol}: no data")
            continue
        stats = run_backtest(df, symbol, config)
        print(f"\n{symbol}  ({stats['bars_tested']} bars)")
        print(f"  Total return : {stats['total_return_pct']:+.2f}%")
        print(f"  Realized PnL : {stats['realized_pnl']:+.2f}")
        print(f"  Trades       : {stats['total_trades']}")
        print(f"  Win rate     : {stats['win_rate']:.1f}%")
        print(f"  Profit factor: {stats['profit_factor']:.2f}")
        print(f"  Max drawdown : {stats['max_drawdown_pct']:.2f}%")

    print("\n" + "=" * 62)
    print("Past performance does NOT guarantee future results. Trade carefully.\n")


if __name__ == "__main__":
    main()
