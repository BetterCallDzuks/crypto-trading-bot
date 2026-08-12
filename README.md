# Crypto Trading Bot

An automated trading bot for **Bitcoin, Ethereum and XRP** with a live web
dashboard. It trades a transparent, multi-signal strategy with strict risk
management, and runs in **paper-trading mode by default** so you can validate
everything with simulated money before risking a single cent.

> ⚠️ **Read this first.** No trading bot can guarantee profit. Automated
> crypto trading carries a **substantial risk of loss**, and markets can move
> against any strategy. This software is provided for education and research.
> Start in paper mode, backtest thoroughly, and never trade money you cannot
> afford to lose. You are solely responsible for any real trades you enable.

---

## Highlights

- **Trades BTC / ETH / XRP** on any [ccxt](https://github.com/ccxt/ccxt)-supported
  exchange (Binance, Bybit, Kraken, OKX, Coinbase, …), spot **or** perpetual.
- **Paper trading by default** using *real live prices* and simulated money —
  realistic fees and slippage included, so results aren't sugar-coated.
- **Transparent strategy** — a weighted ensemble of EMA trend, MACD momentum,
  RSI, Bollinger bands and an ADX trend-strength filter. No black boxes.
- **Serious risk management** — fixed-fractional position sizing, ATR-based
  stops & targets, trailing stops, position caps, and a **max-drawdown circuit
  breaker** that halts trading before a bad run becomes a disaster.
- **Backtester** — replays the *exact* live logic over historical candles.
- **Web dashboard** — equity curve, open positions, live signals, trade
  history, and start/stop controls.
- **Minimum maintenance** — one Python process, one SQLite file, no database
  server, no build step, no compiled dependencies.

## Architecture

```
run.py                      # launches dashboard (+ optional engine autostart)
config.yaml                 # strategy & risk parameters (safe to commit)
.env                        # secrets & mode (never commit)
app/
  config.py                 # settings + config loading
  exchange.py               # ccxt wrapper: market data + guarded live orders
  indicators.py             # EMA / RSI / MACD / ATR / ADX / Bollinger (pure pandas)
  strategy.py               # the multi-signal ensemble
  risk.py                   # position sizing, stops, circuit breaker
  portfolio.py              # simulated account (fees + slippage)
  engine.py                 # the trading loop (background thread)
  backtest.py               # historical replay / validation
  database.py               # SQLite ledger + equity curve
  web/server.py             # FastAPI dashboard + JSON API
  web/static/               # single-page dashboard UI
tests/                      # unit tests (no network needed)
```

The same `Strategy`, `RiskManager` and `PaperPortfolio` classes drive **both**
the backtester and the live engine — so what you test is what you trade.

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure (optional — paper mode needs no keys)
cp .env.example .env

# 3. Backtest the strategy on real history first
python -m app.backtest --symbol BTC/USDT --timeframe 1h --limit 1500

# 4. Launch the dashboard (paper mode)
python run.py --autostart
#   open http://localhost:8000
```

> **Note:** steps 3 and 4 need outbound internet access to your exchange's
> public API. Some restricted/sandboxed networks block exchange endpoints; run
> on a normal network or your own server.

## How it decides to trade

Each cycle, for every symbol, five independent voters each score the market in
`[-1, +1]` (bearish … bullish):

| Voter | Signal |
|-------|--------|
| Trend | Fast EMA vs slow EMA (muted when the market isn't trending) |
| MACD | Histogram sign and slope (momentum) |
| RSI | Penalises overbought extremes, rewards oversold |
| Bollinger | Position within the volatility envelope (mean reversion) |
| ADX direction | Directional confirmation, only counts in a real trend |

The weighted sum is the **signal score**. A long opens above
`+min_signal_score`, a short below `-min_signal_score` (perpetual only — spot is
long-only). Position size is set so that hitting the ATR-based stop loses only
`risk_per_trade` (default **1%**) of equity. Every position gets a stop, a
take-profit at `reward_risk_ratio`× the risk, and a trailing stop once in
profit.

If equity falls `max_drawdown_halt` (default **15%**) below its peak, the
**circuit breaker** stops all new trades.

## Configuration

- **`config.yaml`** — symbols, timeframe, and all strategy/risk parameters.
  Conservative defaults; tune only after backtesting.
- **`.env`** — trading mode, exchange, API keys, dashboard token. See
  `.env.example`.

### Going live (only when you're ready)

Live trading is intentionally hard to enable by accident. **Both** are required:

```bash
TRADING_MODE=live
TRADING_LIVE_CONFIRM=I_UNDERSTAND_THE_RISK
EXCHANGE_API_KEY=...        # create with TRADE permission only — NEVER withdrawals
EXCHANGE_API_SECRET=...
```

Recommended path: **paper → exchange testnet (`EXCHANGE_SANDBOX=true`) → live
with tiny size.** Secure the dashboard with `DASHBOARD_TOKEN` if it's reachable
from the internet.

## Dashboard API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/status` | Full snapshot: equity, positions, live signals |
| GET | `/api/trades` | Recent closed trades |
| GET | `/api/equity` | Equity-curve points |
| POST | `/api/start` / `/api/stop` | Control the engine |

If `DASHBOARD_TOKEN` is set, pass `?token=…` or `Authorization: Bearer …`.

## Tests

```bash
pytest -q
```

Covers indicators, strategy signals, position sizing, the reward/risk ratio,
the drawdown circuit breaker, and portfolio accounting — all offline.

## Deploying for minimum maintenance

It's one process. Any of these work well:

```bash
# systemd, Docker, or a simple process manager
python run.py --autostart
```

Keep `data/bot.db` on persistent storage to retain trade history across
restarts. That's the whole maintenance story.

## Disclaimer

This project is for educational purposes. It is **not** financial advice.
Cryptocurrency trading is high-risk; you can lose your entire capital. The
authors accept no liability for any losses. Trade responsibly.
