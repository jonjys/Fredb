# app/config.py
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
    symbols_csv: str = Field(default="BTC/USDT,ETH/USDT,SOL/USDT", validation_alias="SYMBOLS")
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
    # Must clear round_trip_cost_pct() * min_tp_cost_multiple (0.3% * 3 =
    # 0.9% at the fee/slippage defaults below) — RiskManager.is_take_profit_worth_it()
    # is checked at bot startup and refuses to run otherwise. 0.6% used to be
    # the default and silently failed that check: trailing (see
    # trailing_activate_pct) was cutting winners before they ever reached a
    # target that was already too thin to clear fees.
    take_profit_pct: float = 1.0
    trailing_stop_pct: float = 0.3
    stop_loss_pct: float = 0.5  # keeps take_profit_pct at a 2:1 reward:risk ratio
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
    # On an unfilled post-only entry, cancel and repost this many times at a
    # fresh top-of-book price before giving up — never crosses the spread
    # (still GTX/postOnly every attempt), just refreshes a stale quote as
    # price drifts, instead of walking away after a single attempt.
    post_only_max_retries: int = 2
    # An entry fill's fee rate exceeding maker_fee_pct by this multiple gets
    # logged as TAKER_LEAKAGE and alerted. This should structurally never
    # fire — GTX orders can only fill as maker or get rejected — so seeing
    # it at all means something upstream (a fee-schedule change, an order
    # type regression) needs a human, not an autonomous pause. See
    # bot.py/futures_bot.py._check_taker_leakage.
    taker_leakage_fee_multiple: float = 1.2

    # ---- Volatility-aware risk throttle (RiskManager.size_position) --------
    # A fixed risk_pct at 0.3% ATR and at 0.9% ATR isn't the same real
    # exposure — the wider stop from size_position's own atr_pct*atr_multiplier
    # term already makes qty *smaller* on volatile bars, but not smaller
    # dollar risk. On a news-spike bar the two effects don't fully cancel;
    # this throttle cuts risk_amount itself when ATR% crosses into
    # "unusually volatile" territory as an extra margin of safety.
    high_volatility_atr_pct: float = 1.5
    high_volatility_risk_multiplier: float = 0.5
    # Hard ceiling on gross notional exposure per position, independent of
    # the risk-based qty calc above — a backstop against tail/gap risk
    # (an exchange outage, a flash crash the modeled stop can't react to)
    # rather than the everyday risk-per-trade control.
    max_notional_pct_of_equity: float = 0.20

    # ---- Regime filters (orderbook + BTC dominance) -------------------------
    # Skip a long when the order book is this lopsided toward asks (heavy
    # sell pressure at the touch) even if the strategy signal says long, and
    # the mirror for shorts. 1.0 = balanced book; <0.7 means asks
    # outweigh bids by ~43% or more.
    regime_orderbook_imbalance_min: float = 0.7
    regime_orderbook_depth_levels: int = 5
    # BTC dominance (BTC's share of total crypto market cap) — a market-wide
    # "risk-on altcoins vs risk-off into BTC" proxy that a single symbol's
    # own order book can't tell you. Sourced from CoinGecko's free, no-key
    # /api/v3/global endpoint (see app/regime.py) since Binance/ccxt has no
    # dominance data. Fails open (gate skipped, not blocked) on fetch error —
    # this is a filter, not a dependency the bot should ever halt for.
    regime_btc_dominance_enabled: bool = True
    regime_btc_dominance_move_threshold_pct: float = 0.5
    regime_btc_dominance_refresh_seconds: float = 900.0

    # Trailing-stop activation threshold, independent of take_profit_pct.
    # Was 0.25% — well under a third of take_profit_pct — which meant
    # trailing kicked in almost immediately and clipped most winners at a
    # fraction of the nominal TP long before price could reach it. Now set
    # to 70% of the (raised) take_profit_pct so a trade has room to actually
    # run before trailing starts protecting the gain.
    trailing_activate_pct: float = 0.7

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
        default="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT", validation_alias="FUTURES_SYMBOLS"
    )
    # "dynamic" scans the top-N most liquid USDT-M perpetuals by 24h volume
    # instead of a fixed list — was the default while the strategy was being
    # validated broadly, but a mean-reversion engine on leverage is exactly
    # the setup that gets hurt most by thin-book altcoin slippage, so the
    # default is now "fixed" on BTC/ETH/SOL only. "dynamic" is still
    # available (and still volume-floor-gated) for anyone who wants it back.
    futures_symbol_mode: Literal["fixed", "dynamic"] = "fixed"
    futures_dynamic_top_n: int = 10
    # Liquidity floor for the dynamic scan, in 24h USDT volume — this is the
    # main guard against trading thin, easily-manipulated markets with
    # leverage. Raised from $5M to $50M after a live paper-mode audit found
    # low-cap/high-volatility pairs (ZEC, NEAR, UNI) in the dynamic universe
    # at full leverage — $5M was too permissive a floor for a leveraged
    # mean-reversion engine; $50M keeps it to genuinely deep books.
    futures_min_24h_volume_usd: float = 50_000_000.0
    # Add tickers here (comma-separated) if a legitimate coin isn't on the
    # built-in allowlist in exchange.py's KNOWN_CRYPTO_BASE_ASSETS — do not
    # widen that allowlist's matching logic itself, extend the list.
    futures_extra_allowed_symbols_csv: str = Field(
        default="", validation_alias="FUTURES_EXTRA_ALLOWED_SYMBOLS"
    )
    # Explicit blacklist applied to the dynamic (top-volume) scan only —
    # symbols here are excluded even if they clear futures_min_24h_volume_usd
    # and the KNOWN_CRYPTO_BASE_ASSETS allowlist. Fixed-mode FUTURES_SYMBOLS
    # is an explicit, deliberate choice and is never filtered against this
    # list. Default set from a live audit: high-volatility pairs where a
    # single ATR-scale move can outrun the per-trade leverage-safety clamp
    # (RiskManager.max_safe_leverage) faster than the poll loop reacts.
    futures_excluded_symbols_csv: str = Field(
        default="ZEC/USDT:USDT,NEAR/USDT:USDT,UNI/USDT:USDT,LUNC/USDT:USDT",
        validation_alias="FUTURES_EXCLUDED_SYMBOLS",
    )
    futures_leverage_default: float = 8.0
    # Was 50 (Binance's own ceiling) — lowered to 20 after a live audit
    # found the dashboard's manual leverage override set to 50x on a
    # dynamic universe that included low-liquidity pairs. Risk-per-trade
    # itself doesn't change with leverage (RiskManager.size_position is
    # leverage-agnostic — see size_position_leveraged's docstring), but
    # higher leverage still means a smaller adverse move reaches the
    # exchange's liquidation price, which is the actual thing this caps.
    futures_max_leverage: float = 20.0
    # "Auto" leverage mode (the default) recomputes the leverage ceiling
    # every symbol-refresh cycle from BTC's current ATR% — calm markets get
    # a ceiling near the max of this band, choppier markets get pulled down
    # toward the min. Per-trade leverage is still always clamped further by
    # RiskManager.max_safe_leverage() regardless of what this picks.
    futures_auto_leverage_min: float = 5.0
    futures_auto_leverage_max: float = 10.0
    futures_paper_starting_balance: float = 1000.0

    # ---- Nightly autotune (app/autotune.py) ----------------------------------
    # Runs a walkforward grid-search over recent data once a day and reports
    # whether a different take_profit_pct would have scored a meaningfully
    # better profit factor. Deliberately suggest-only by default
    # (autotune_auto_apply=False): a 14-day window is a small, noisy sample,
    # and auto-mutating a live bot's risk parameters from it is a real
    # overfitting/whipsaw risk in its own right — the dashboard surfaces the
    # recommendation, a human decides whether to apply it. Set
    # autotune_auto_apply=true only once you've watched a few nights of
    # suggestions and trust them.
    autotune_enabled: bool = True
    autotune_auto_apply: bool = False
    autotune_hour_utc: int = 2
    autotune_lookback_days: int = 14
    # Every candidate here must clear RiskManager.is_take_profit_worth_it()'s
    # floor (round_trip_cost_pct * min_tp_cost_multiple, 0.9% at current fee
    # defaults) — the grid search also filters at runtime in case fee
    # settings change later, but keep this list itself already-safe so a
    # config read alone doesn't suggest a value the bot would refuse to run.
    autotune_tp_candidates_csv: str = Field(
        default="1.0,1.2,1.4", validation_alias="AUTOTUNE_TP_CANDIDATES"
    )
    # New candidate must beat the current TP's profit factor by at least
    # this multiple to be worth suggesting — guards against "improvement"
    # that's really just noise around a wash.
    autotune_min_pf_improvement_multiple: float = 1.2

    # Push notifications (app/notifications.py) — critical-event alerts sent
    # to Discord and/or Telegram. Both are optional and independent; set
    # either, both, or neither. Empty (the default) means notifications are
    # silently disabled rather than erroring, so this never blocks a deploy
    # that hasn't configured them yet.
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # A stop/trailing-stop fill more than this far from the level it was
    # supposed to trigger at gets flagged as an alert-worthy slippage event.
    # Paper mode's fixed slippage_buffer_pct model will rarely reach this —
    # it matters most once promoted to testnet/live, where a real fill can
    # gap past the trigger on a thin book or a fast move.
    slippage_alert_pct: float = 0.15

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
    def futures_excluded_symbols(self) -> List[str]:
        return [s.strip() for s in self.futures_excluded_symbols_csv.split(",") if s.strip()]

    @property
    def autotune_tp_candidates(self) -> List[float]:
        return [float(s.strip()) for s in self.autotune_tp_candidates_csv.split(",") if s.strip()]

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
