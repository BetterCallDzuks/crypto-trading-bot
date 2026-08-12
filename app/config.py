"""Configuration loading.

Two layers:
  * Secrets & mode  -> environment variables (.env)  -> `Settings`
  * Strategy & risk -> config.yaml                    -> `BotConfig`

Keeping them separate means credentials never live in a file that is safe to
commit, while the tunable trading parameters can be version-controlled.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
LIVE_CONFIRM_PHRASE = "I_UNDERSTAND_THE_RISK"


class Settings(BaseSettings):
    """Runtime secrets & mode, sourced from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    trading_mode: str = "paper"          # "paper" | "live"
    trading_live_confirm: str = ""

    exchange_id: str = "binance"
    market_type: str = "spot"            # "spot" | "swap"
    exchange_api_key: str = ""
    exchange_api_secret: str = ""
    exchange_api_password: str = ""
    exchange_sandbox: bool = False

    web_host: str = "0.0.0.0"
    web_port: int = 8000
    dashboard_token: str = ""

    @property
    def is_live(self) -> bool:
        return self.trading_mode.lower() == "live"

    @property
    def live_confirmed(self) -> bool:
        """Live trading is only permitted with the explicit confirm phrase."""
        return self.is_live and self.trading_live_confirm == LIVE_CONFIRM_PHRASE


class RiskConfig(BaseModel):
    risk_per_trade: float = 0.01
    max_open_positions: int = 3
    atr_period: int = 14
    atr_stop_multiplier: float = 2.5
    reward_risk_ratio: float = 2.0
    trailing_atr_multiplier: float = 3.0
    max_drawdown_halt: float = 0.15
    leverage: int = 2


class StrategyConfig(BaseModel):
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_overbought: float = 70
    rsi_oversold: float = 30
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_period: int = 14
    adx_trend_threshold: float = 20
    bb_period: int = 20
    bb_std: float = 2.0
    min_signal_score: float = 0.6


class BotConfig(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "XRP/USDT"])
    timeframe: str = "1h"
    poll_interval_seconds: int = 60
    paper_starting_balance: float = 10000
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)


def load_settings() -> Settings:
    return Settings()


def load_bot_config(path: str | Path = ROOT / "config.yaml") -> BotConfig:
    path = Path(path)
    if not path.exists():
        return BotConfig()
    data = yaml.safe_load(path.read_text()) or {}
    return BotConfig(**data)
