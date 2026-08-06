"""Central configuration, loaded from environment variables / .env."""
from __future__ import annotations

from typing import List, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # Runtime
    bot_mode: Literal["paper", "testnet", "live"] = "paper"
    exchange_id: str = "binance"
    # Stored as raw CSV strings (not List[str]) so pydantic-settings doesn't
    # attempt JSON-decoding the env var; see `symbols` / `cors_origins` props.
    symbols_csv: str = Field(default="BTC/USDT,ETH/USDT", validation_alias="SYMBOLS")
    cors_origins_csv: str = Field(
        default="http://localhost:3000", validation_alias="CORS_ORIGINS"
    )
    timeframe: str = "1m"

    # Exchange credentials
    binance_api_key: str = ""
    binance_api_secret: str = ""
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    coinbase_password: str = ""

    # Risk management
    max_risk_per_trade_pct: float = 1.0
    max_concurrent_positions: int = 3
    take_profit_pct: float = 0.6
    trailing_stop_pct: float = 0.3
    stop_loss_pct: float = 0.4
    atr_multiplier: float = 1.5
    max_daily_loss_pct: float = 5.0
    taker_fee_pct: float = 0.1
    slippage_buffer_pct: float = 0.05
    paper_starting_balance: float = 1000.0

    poll_interval_seconds: float = 5.0

    # Futures (leveraged) trading — opt-in, off by default. Deliberately a
    # separate on/off switch and mode from the spot bot above so the two can
    # be enabled/promoted to testnet/live independently of each other.
    futures_enabled: bool = False
    futures_mode: Literal["paper", "testnet", "live"] = "paper"
    futures_exchange_id: str = "binanceusdm"
    futures_symbols_csv: str = Field(
        default="BTC/USDT:USDT,ETH/USDT:USDT", validation_alias="FUTURES_SYMBOLS"
    )
    # "dynamic" scans the top-N most liquid USDT-M perpetuals by 24h volume
    # instead of a fixed list, so the bot isn't limited to BTC/ETH — any
    # sufficiently liquid pair (ADA, SOL, DOGE, meme coins once they have
    # real volume, etc.) becomes tradeable automatically. "fixed" uses
    # futures_symbols_csv above, unchanged from the original behavior.
    futures_symbol_mode: Literal["fixed", "dynamic"] = "dynamic"
    futures_dynamic_top_n: int = 10
    # Liquidity floor for the dynamic scan, in 24h USDT volume — this is the
    # main guard against trading thin, easily-manipulated markets with
    # leverage. Binance's most liquid pairs (BTC/ETH) trade billions/day;
    # $5M is a conservative floor well above where slippage/manipulation
    # risk becomes a serious concern, while still being low enough to admit
    # popular altcoins and meme coins once they have genuine volume.
    futures_min_24h_volume_usd: float = 5_000_000.0
    # Add tickers here (comma-separated) if a legitimate coin isn't on the
    # built-in allowlist in exchange.py's KNOWN_CRYPTO_BASE_ASSETS — do not
    # widen that allowlist's matching logic itself, extend the list.
    futures_extra_allowed_symbols_csv: str = Field(
        default="", validation_alias="FUTURES_EXTRA_ALLOWED_SYMBOLS"
    )
    futures_leverage_default: float = 5.0
    futures_max_leverage: float = 50.0
    futures_paper_starting_balance: float = 1000.0

    # Security
    dashboard_api_token: str = "change-me-to-a-long-random-secret"

    # Persistence / logging
    database_path: str = "data/bot.db"
    log_level: str = "INFO"
    port: int = 8000

    @property
    def symbols(self) -> List[str]:
        return [s.strip() for s in self.symbols_csv.split(",") if s.strip()]

    @property
    def cors_origins(self) -> List[str]:
        return [s.strip() for s in self.cors_origins_csv.split(",") if s.strip()]

    @property
    def futures_symbols(self) -> List[str]:
        return [s.strip() for s in self.futures_symbols_csv.split(",") if s.strip()]

    @property
    def exchange_api_key(self) -> str:
        return {"binance": self.binance_api_key, "coinbase": self.coinbase_api_key}.get(
            self.exchange_id, ""
        )

    @property
    def exchange_api_secret(self) -> str:
        return {"binance": self.binance_api_secret, "coinbase": self.coinbase_api_secret}.get(
            self.exchange_id, ""
        )


settings = Settings()
