"""Exchange connectivity via ccxt.

Provides a thin, uniform interface used by the engine and backtester:
  * fetch_ohlcv() — historical candles (works without API keys, public data)
  * fetch_price() — latest price
  * create_market_order() — LIVE order placement (guarded)

Market data works for any ccxt exchange with no credentials, so paper trading
runs against *real live prices* while never touching a real account.
"""
from __future__ import annotations

import logging

import pandas as pd

try:
    import ccxt  # type: ignore
except ImportError:  # pragma: no cover - ccxt is a hard dep, but stay graceful
    ccxt = None

from .config import Settings
from .models import Side

log = logging.getLogger("exchange")

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class ExchangeClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = self._build_client()

    def _build_client(self):
        if ccxt is None:
            raise RuntimeError("ccxt is not installed. Run: pip install -r requirements.txt")
        exchange_id = self.settings.exchange_id
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Unknown exchange id: {exchange_id!r}")

        params: dict = {
            "enableRateLimit": True,
            "options": {"defaultType": self.settings.market_type},
        }
        # Only attach credentials for live trading.
        if self.settings.is_live:
            params["apiKey"] = self.settings.exchange_api_key
            params["secret"] = self.settings.exchange_api_secret
            if self.settings.exchange_api_password:
                params["password"] = self.settings.exchange_api_password

        client = getattr(ccxt, exchange_id)(params)
        if self.settings.exchange_sandbox:
            try:
                client.set_sandbox_mode(True)
            except Exception as exc:  # pragma: no cover
                log.warning("Sandbox mode unavailable for %s: %s", exchange_id, exc)
        return client

    # --- Market data --------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        raw = self._client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=OHLCV_COLUMNS)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df.set_index("datetime")

    def fetch_price(self, symbol: str) -> float:
        ticker = self._client.fetch_ticker(symbol)
        return float(ticker["last"])

    # --- Live orders (guarded) ---------------------------------------------
    def create_market_order(self, symbol: str, side: Side, quantity: float) -> dict:
        if not self.settings.live_confirmed:
            raise PermissionError(
                "Live order blocked. Set TRADING_MODE=live and "
                "TRADING_LIVE_CONFIRM=I_UNDERSTAND_THE_RISK to enable real trading."
            )
        ccxt_side = "buy" if side == Side.LONG else "sell"
        log.warning("LIVE ORDER: %s %s %s", ccxt_side, quantity, symbol)
        return self._client.create_order(symbol, "market", ccxt_side, quantity)
