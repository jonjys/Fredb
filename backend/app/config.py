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
