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

    # Mean-reversion strategy (app/mean_reversion.py)
    mr_bb_period: int = 20
    mr_bb_std: float = 2.2
    mr_rsi_period: int = 14
    mr_rsi_oversold: float = 28.0
    mr_rsi_overbought: float = 72.0
    mr_volume_sma_period: int = 20
    mr_min_distance_std: float = 1.1
    htf_timeframe: str = "15m"
    htf_ema_period: int = 50
    htf_lookback_bars: int = 80

    # Post-only limit execution (app/exchange.py order helpers)
    post_only_timeout_seconds: float = 10.0
    post_only_poll_interval_seconds: float = 1.0
    maker_fee_pct: float = 0.02  # Binance USDT-M futures maker rate; spot maker == taker by default

    # Trailing-stop activation threshold, independent of take_profit_pct — the
    # mean-reversion exit spec activates trailing at a smaller unrealized gain
    # than the take-profit target itself, unlike the original scalper (which
    # only started trailing once TP was already hit).
    trailing_activate_pct: float = 0.25

    # Consecutive-loss circuit breaker (on top of the daily kill switch)
    consecutive_loss_threshold: int = 4
    consecutive_loss_pause_minutes: float = 45.0
    consecutive_loss_reduced_trades: int = 3
    consecutive_loss_size_reduction_pct: float = 50.0

    # Cost-floor multiple for is_take_profit_worth_it() — TP must clear the
    # round-trip cost by at least this factor, not just exceed it.
    min_tp_cost_multiple: float = 3.0

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
    futures_leverage_default: float = 8.0
    futures_max_leverage: float = 50.0
    # "Auto" leverage mode (the default) recomputes the leverage ceiling
    # every symbol-refresh cycle from BTC's current ATR% — calm markets get
    # a ceiling near the max of this band, choppier markets get pulled down
    # toward the min. Per-trade leverage is still always clamped further by
    # RiskManager.max_safe_leverage() regardless of what this picks.
    futures_auto_leverage_min: float = 5.0
    futures_auto_leverage_max: float = 10.0
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
