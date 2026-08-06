"""Futures (leveraged) trading bot orchestration loop.

Structurally mirrors bot.py (spot), but a separate class rather than a
generalized one: entry/exit mechanics genuinely differ (leverage sizing,
margin accounting, exchange-native stop/take-profit orders instead of
poll-only market sells) and keeping them separate avoids risking a subtle
regression in the already-live spot bot while building this.

Safety model, in one sentence: risk-per-trade is identical to spot
regardless of leverage (RiskManager.size_position is leverage-agnostic);
leverage only changes margin efficiency, and the requested leverage is
always clamped down (never up) so the stop-loss fires before the exchange's
liquidation engine would.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Dict, List, Optional

from app.config import Settings
from app.exchange import FuturesBroker, build_futures_broker
from app.models import FuturesPosition, FuturesTrade
from app.risk import RiskManager
from app.state_store import StateStore
from app.strategy import ScalpingStrategy, _atr

logger = logging.getLogger("tradingbot.futures_bot")

# How often the dynamic (top-volume) symbol universe and the auto-leverage
# ceiling are refreshed. Doing this every poll tick would mean extra API
# calls every few seconds for no benefit — market-wide volatility and the
# set of liquid pairs don't meaningfully change minute to minute.
DYNAMIC_SYMBOL_REFRESH_SECONDS = 300

# Auto leverage mode maps BTC's current ATR% to a ceiling within
# [futures_auto_leverage_min, futures_auto_leverage_max]: calm markets (at
# or below the low bound) get the top of the band, choppy markets (at or
# above the high bound) get pulled down to the bottom of it, linear
# interpolation in between. This is a market-wide regime proxy, not
# per-symbol — the per-trade safety clamp (RiskManager.max_safe_leverage)
# is what actually accounts for each specific trade's own volatility.
AUTO_LEVERAGE_ATR_LOW_PCT = 0.15
AUTO_LEVERAGE_ATR_HIGH_PCT = 1.0


class FuturesTradingBot:
    def __init__(self, settings: Settings, store: StateStore):
        self.settings = settings
        self.store = store
        self.broker: FuturesBroker = build_futures_broker(settings)
        self.strategy = ScalpingStrategy()
        self.risk = RiskManager(settings)
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._last_prices: Dict[str, float] = {}
        self._dynamic_symbols: List[str] = []
        self._dynamic_symbols_refreshed_at: float = 0.0
        self._leverage_refreshed_at: float = 0.0

    async def start_background_loop(self) -> None:
        await asyncio.to_thread(self.store.init, self.settings.futures_paper_starting_balance)
        state = await self.store.get_state()
        if self.settings.futures_mode == "paper":
            self.broker.quote_balance = state.paper_balance  # type: ignore[attr-defined]
        self._task = asyncio.create_task(self._run_loop())
        symbol_mode_desc = (
            f"dynamic (top {self.settings.futures_dynamic_top_n} by 24h volume, "
            f"min ${self.settings.futures_min_24h_volume_usd:,.0f})"
            if self.settings.futures_symbol_mode == "dynamic"
            else f"fixed ({','.join(self.settings.futures_symbols)})"
        )
        logger.info(
            "Futures bot initialized: mode=%s exchange=%s symbols=%s leverage_default=%sx",
            self.settings.futures_mode,
            self.settings.futures_exchange_id,
            symbol_mode_desc,
            self.settings.futures_leverage_default,
        )

    async def shutdown(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
        await self.broker.close()

    # ---- Control endpoints called from the API --------------------------
    async def set_running(self, running: bool) -> None:
        await self.store.update_state(running=running)
        logger.info("Futures bot %s by dashboard", "STARTED" if running else "STOPPED")

    async def set_leverage_default(self, leverage: float) -> None:
        """Explicit manual override — switches out of auto mode so the bot
        stops rewriting this value on its own until the user re-enables it."""
        leverage = max(1.0, min(leverage, self.settings.futures_max_leverage))
        await self.store.update_state(leverage=leverage, leverage_mode="manual")
        logger.info("Futures leverage manually set to %sx by dashboard (auto mode disabled)", leverage)

    async def set_leverage_mode(self, mode: str) -> None:
        if mode not in ("auto", "manual"):
            raise ValueError(f"invalid leverage mode: {mode!r}")
        await self.store.update_state(leverage_mode=mode)
        logger.info("Futures leverage mode set to %s by dashboard", mode)
        if mode == "auto":
            self._leverage_refreshed_at = 0.0  # force a recompute on the next tick

    def _map_atr_to_leverage_ceiling(self, atr_pct: float) -> float:
        band_min = self.settings.futures_auto_leverage_min
        band_max = self.settings.futures_auto_leverage_max
        if atr_pct <= AUTO_LEVERAGE_ATR_LOW_PCT:
            return band_max
        if atr_pct >= AUTO_LEVERAGE_ATR_HIGH_PCT:
            return band_min
        span = AUTO_LEVERAGE_ATR_HIGH_PCT - AUTO_LEVERAGE_ATR_LOW_PCT
        frac = (atr_pct - AUTO_LEVERAGE_ATR_LOW_PCT) / span
        return band_max - frac * (band_max - band_min)

    async def _maybe_refresh_auto_leverage(self) -> None:
        state = await self.store.get_state()
        if state.leverage_mode != "auto":
            return
        now = time.time()
        if self._leverage_refreshed_at and now - self._leverage_refreshed_at < DYNAMIC_SYMBOL_REFRESH_SECONDS:
            return
        try:
            df = await self.broker.get_ohlcv("BTC/USDT:USDT", self.settings.timeframe, limit=30)
            last_close = float(df["close"].iloc[-1])
            last_atr = float(_atr(df, 14).iloc[-1])
            atr_pct = (last_atr / last_close * 100) if last_close else 0.0
            ceiling = round(self._map_atr_to_leverage_ceiling(atr_pct), 1)
            await self.store.update_state(leverage=ceiling)
            self._leverage_refreshed_at = now
            logger.info(
                "Auto leverage ceiling recomputed from BTC ATR%%=%.3f%%: %sx", atr_pct, ceiling
            )
        except Exception:
            logger.exception("Failed to refresh auto leverage ceiling — keeping previous value")

    async def emergency_kill(self, reason: str = "manual kill switch") -> None:
        await self.store.update_state(running=False, kill_switch=True, kill_switch_reason=reason)
        logger.warning(
            "FUTURES EMERGENCY KILL SWITCH ACTIVATED: %s — closing all open positions", reason
        )
        open_positions = await self.store.get_open_positions()
        for position in open_positions:
            try:
                await self._close_position(position, "emergency_kill")
            except Exception:
                logger.exception("Failed to close futures position %s during kill switch", position.id)

    async def reset_kill_switch(self) -> None:
        await self.store.update_state(kill_switch=False, kill_switch_reason="")
        logger.info("Futures kill switch reset by dashboard")

    # ---- Core loop --------------------------------------------------------
    async def _run_loop(self) -> None:
        while not self._stopping:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled error in futures bot loop tick — continuing")
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _tick(self) -> None:
        await self._roll_daily_window_if_needed()
        state = await self.store.get_state()

        open_positions = await self.store.get_open_positions()
        for position in open_positions:
            await self._manage_position(position)

        equity = await self._compute_equity()
        await self.store.record_equity(equity, equity - state.daily_start_equity)

        if not state.kill_switch:
            kill_reason = self.risk.check_daily_drawdown(equity, state.daily_start_equity)
            if kill_reason:
                await self.emergency_kill(kill_reason)
                return

        state = await self.store.get_state()
        if not state.running or state.kill_switch:
            return

        await self._maybe_refresh_auto_leverage()
        state = await self.store.get_state()  # re-read in case the ceiling just changed

        open_positions = await self.store.get_open_positions()
        if not self.risk.can_open_new_position(len(open_positions), state.kill_switch):
            return

        open_symbols = {p.symbol for p in open_positions}
        for symbol in await self._get_active_symbols():
            if symbol in open_symbols:
                continue
            open_positions = await self.store.get_open_positions()
            if not self.risk.can_open_new_position(len(open_positions), state.kill_switch):
                break
            await self._evaluate_entry(symbol, equity, state.leverage)

    async def _get_active_symbols(self) -> List[str]:
        if self.settings.futures_symbol_mode != "dynamic":
            return self.settings.futures_symbols

        now = time.time()
        stale = now - self._dynamic_symbols_refreshed_at > DYNAMIC_SYMBOL_REFRESH_SECONDS
        if stale or not self._dynamic_symbols:
            try:
                symbols = await self.broker.get_top_symbols(
                    self.settings.futures_dynamic_top_n, self.settings.futures_min_24h_volume_usd
                )
                if symbols:
                    self._dynamic_symbols = symbols
                    self._dynamic_symbols_refreshed_at = now
                    logger.info(
                        "Futures dynamic symbol universe refreshed (top %s by 24h volume, "
                        "min $%.0f): %s",
                        self.settings.futures_dynamic_top_n,
                        self.settings.futures_min_24h_volume_usd,
                        ", ".join(symbols),
                    )
                else:
                    logger.warning(
                        "Dynamic symbol scan returned no pairs above the $%.0f volume floor",
                        self.settings.futures_min_24h_volume_usd,
                    )
            except Exception:
                logger.exception(
                    "Failed to refresh dynamic futures symbol universe — keeping previous list"
                )
        # Fall back to the configured fixed list if the dynamic scan has
        # never once succeeded (e.g. first tick after startup failed).
        return self._dynamic_symbols or self.settings.futures_symbols

    async def _roll_daily_window_if_needed(self) -> None:
        state = await self.store.get_state()
        today = dt.date.today().isoformat()
        if state.daily_date != today:
            equity = await self._compute_equity()
            await self.store.update_state(
                daily_date=today, daily_start_equity=equity, kill_switch=False, kill_switch_reason=""
            )
            logger.info("New futures trading day started. Daily start equity=%.2f", equity)

    async def _compute_equity(self) -> float:
        free_balance = await self.broker.get_quote_balance()
        open_positions = await self.store.get_open_positions()
        positions_equity = 0.0
        for position in open_positions:
            try:
                price = await self.broker.get_price(position.symbol)
                self._last_prices[position.symbol] = price
                unrealized_pnl = (price - position.entry_price) * position.qty
                positions_equity += position.margin_used + unrealized_pnl
            except Exception:
                logger.warning("Could not fetch price for %s, using entry price", position.symbol)
                positions_equity += position.margin_used
        if self.settings.futures_mode == "paper":
            await self.store.update_state(paper_balance=free_balance)
        return free_balance + positions_equity

    async def _evaluate_entry(self, symbol: str, equity: float, requested_leverage: float) -> None:
        try:
            df = await self.broker.get_ohlcv(symbol, self.settings.timeframe, limit=100)
        except Exception:
            logger.exception("Failed to fetch OHLCV for %s", symbol)
            return

        signal = self.strategy.generate_signal(df)
        if signal.action != "buy":
            return

        sizing = self.risk.size_position_leveraged(
            equity, signal.close, signal.atr, signal.atr_pct, requested_leverage,
            self.settings.futures_max_leverage,
        )
        if sizing is None or sizing.qty <= 0:
            return

        free_balance = await self.broker.get_quote_balance()
        if sizing.margin_required_quote > free_balance:
            logger.info(
                "%s: insufficient free margin for entry (need %.2f, have %.2f)",
                symbol, sizing.margin_required_quote, free_balance,
            )
            return

        try:
            fill = await self.broker.open_long(
                symbol, sizing.qty, sizing.leverage, sizing.stop_loss_price, sizing.take_profit_price
            )
        except Exception:
            logger.exception("Futures buy order failed for %s", symbol)
            return

        position = FuturesPosition(
            symbol=symbol,
            side="long",
            status="open",
            leverage=sizing.leverage,
            entry_price=fill.price,
            qty=fill.qty,
            margin_used=sizing.margin_required_quote,
            liquidation_price=sizing.liquidation_price,
            stop_loss_price=sizing.stop_loss_price,
            take_profit_price=sizing.take_profit_price,
            trailing_active=False,
            trailing_high=fill.price,
            stop_order_id=fill.stop_order_id,
            take_profit_order_id=fill.take_profit_order_id,
            opened_at=time.time(),
        )
        position = await self.store.open_position(position)
        await self.store.record_trade(
            FuturesTrade(
                position_id=position.id,
                symbol=symbol,
                side="buy",
                trade_type="entry",
                price=fill.price,
                qty=fill.qty,
                leverage=sizing.leverage,
                fee_quote=fill.fee_quote,
            )
        )
        logger.info(
            "OPENED %s qty=%.6f entry=%.4f leverage=%sx margin=%.2f SL=%.4f "
            "(liq~%.4f) TP=%.4f (%s)",
            symbol, fill.qty, fill.price, sizing.leverage, sizing.margin_required_quote,
            sizing.stop_loss_price, sizing.liquidation_price, sizing.take_profit_price, signal.reason,
        )

    async def _manage_position(self, position: FuturesPosition) -> None:
        try:
            price = await self.broker.get_price(position.symbol)
        except Exception:
            logger.warning("Could not fetch price for open futures position %s", position.symbol)
            return
        self._last_prices[position.symbol] = price

        trailing_pct = self.settings.trailing_stop_pct / 100

        if price <= position.stop_loss_price:
            await self._close_position(position, "stop_loss")
            return

        if not position.trailing_active and price >= position.take_profit_price:
            new_high = max(position.trailing_high, price)
            trailing_stop_price = new_high * (1 - trailing_pct)
            try:
                # Switching from "fixed TP" to "let it ride with a trailing
                # stop": cancel the fixed take-profit order first so it can't
                # fire underneath the new, higher trailing stop.
                await self.broker.cancel_order(position.symbol, position.take_profit_order_id)
                new_stop_id = await self.broker.update_stop_order(
                    position.symbol, position.qty, position.stop_order_id, trailing_stop_price
                )
            except Exception:
                logger.exception("Failed to move stop order to trailing level for %s", position.symbol)
                new_stop_id = position.stop_order_id
            await self.store.update_position(
                position.id,
                trailing_active=True,
                trailing_high=new_high,
                stop_loss_price=trailing_stop_price,
                stop_order_id=new_stop_id,
                take_profit_order_id="",
            )
            logger.info(
                "%s hit take-profit trigger (%.4f) — trailing stop activated at %.4f",
                position.symbol, price, trailing_stop_price,
            )
            return

        if position.trailing_active:
            new_high = max(position.trailing_high, price)
            new_trailing_stop = new_high * (1 - trailing_pct)
            if new_high > position.trailing_high and new_trailing_stop > position.stop_loss_price:
                try:
                    new_stop_id = await self.broker.update_stop_order(
                        position.symbol, position.qty, position.stop_order_id, new_trailing_stop
                    )
                except Exception:
                    logger.exception("Failed to ratchet trailing stop for %s", position.symbol)
                    new_stop_id = position.stop_order_id
                await self.store.update_position(
                    position.id,
                    trailing_high=new_high,
                    stop_loss_price=new_trailing_stop,
                    stop_order_id=new_stop_id,
                )

    async def _close_position(self, position: FuturesPosition, reason: str) -> None:
        try:
            fill = await self.broker.close_long(
                position.symbol,
                position.qty,
                position.entry_price,
                position.leverage,
                position.stop_order_id,
                position.take_profit_order_id,
            )
        except Exception:
            logger.exception("Futures sell order failed for %s — will retry next tick", position.symbol)
            return

        pnl_quote = (fill.price - position.entry_price) * fill.qty - fill.fee_quote
        pnl_pct = (pnl_quote / position.margin_used * 100) if position.margin_used else 0.0

        await self.store.close_position(position.id, fill.price, pnl_quote, pnl_pct, reason)
        await self.store.record_trade(
            FuturesTrade(
                position_id=position.id,
                symbol=position.symbol,
                side="sell",
                trade_type="exit",
                price=fill.price,
                qty=fill.qty,
                leverage=position.leverage,
                fee_quote=fill.fee_quote,
            )
        )
        logger.info(
            "CLOSED %s qty=%.6f exit=%.4f pnl=%.4f (%.2f%% on margin) leverage=%sx reason=%s",
            position.symbol, fill.qty, fill.price, pnl_quote, pnl_pct, position.leverage, reason,
        )
