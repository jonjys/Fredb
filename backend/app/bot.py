# app/bot.py
"""Main trading bot orchestration loop.

Design goals:
- Never crash the process: every iteration is wrapped so one bad tick
  (network blip, bad candle, exchange error) logs and continues.
- Open positions are always managed (TP/trailing-stop/SL) even while the
  bot is "stopped" (stopped only blocks *new* entries) or while the kill
  switch is active, so existing risk is never abandoned.
- State (positions, equity, balances) is persisted after every mutation so
  a process restart resumes exactly where it left off.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Dict, Optional

from app.config import Settings
from app.exchange import Broker, build_broker
from app.mean_reversion import MeanReversionStrategy, attach_htf_bias
from app.models import Position, Trade
from app.notifications import Notifier
from app.regime import regime_block_reason
from app.risk import RiskManager
from app.state_store import StateStore

logger = logging.getLogger("tradingbot.bot")


class TradingBot:
    def __init__(self, settings: Settings, store: StateStore):
        self.settings = settings
        self.store = store
        self.broker: Broker = build_broker(settings)
        self.strategy = MeanReversionStrategy(
            bb_period=settings.mr_bb_period,
            bb_std=settings.mr_bb_std,
            rsi_period=settings.mr_rsi_period,
            rsi_oversold=settings.mr_rsi_oversold,
            rsi_overbought=settings.mr_rsi_overbought,
            volume_sma_period=settings.mr_volume_sma_period,
            min_distance_std=settings.mr_min_distance_std,
        )
        self.risk = RiskManager(settings)
        if not self.risk.is_take_profit_worth_it():
            required = self.risk.round_trip_cost_pct() * settings.min_tp_cost_multiple
            raise RuntimeError(
                f"CONFIG ERROR: take_profit_pct={settings.take_profit_pct:.2f}% is below the required "
                f"minimum of {required:.2f}% ({settings.min_tp_cost_multiple:.1f}x round-trip cost of "
                f"{self.risk.round_trip_cost_pct():.2f}%) — refusing to start. Raise take_profit_pct or "
                f"lower fees/slippage_buffer_pct."
            )
        self.notifier = Notifier(settings, source="spot")
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._last_prices: Dict[str, float] = {}
        self._last_skip_reason: Dict[str, str] = {}
        self._maker_entry_attempts = 0
        self._maker_entry_fills = 0
        self._maker_fill_rate_logged_at = time.time()

    async def start_background_loop(self) -> None:
        await asyncio.to_thread(self.store.init, self.settings.paper_starting_balance)
        state = await self.store.get_state()
        if self.settings.bot_mode == "paper":
            # restore simulated wallet balance from last run
            self.broker.quote_balance = state.paper_balance  # type: ignore[attr-defined]
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Trading bot initialized: mode=%s exchange=%s symbols=%s",
            self.settings.bot_mode,
            self.settings.exchange_id,
            ",".join(self.settings.symbols),
        )

    async def shutdown(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
        await self.broker.close()

    # ---- Control endpoints called from the API --------------------------
    async def set_running(self, running: bool) -> None:
        await self.store.update_state(running=running)
        logger.info("Bot %s by dashboard", "STARTED" if running else "STOPPED")

    async def emergency_kill(self, reason: str = "manual kill switch") -> None:
        await self.store.update_state(running=False, kill_switch=True, kill_switch_reason=reason)
        logger.warning("EMERGENCY KILL SWITCH ACTIVATED: %s — closing all open positions", reason)
        # Only the automatic daily-drawdown trip gets a push — see the
        # identical reasoning in futures_bot.py.emergency_kill.
        if reason.startswith("Daily drawdown"):
            asyncio.create_task(
                self.notifier.send(
                    "Daily loss limit hit",
                    f"{reason}\nAll spot positions are being closed and the bot is locked until the "
                    f"next UTC day.",
                    level="critical",
                )
            )
        open_positions = await self.store.get_open_positions()
        for position in open_positions:
            try:
                price = await self.broker.get_price(position.symbol)
                await self._close_position(position, price, "emergency_kill")
            except Exception:
                logger.exception("Failed to close position %s during kill switch", position.id)

    async def reset_kill_switch(self) -> None:
        await self.store.update_state(kill_switch=False, kill_switch_reason="")
        logger.info("Kill switch reset by dashboard")

    # ---- Core loop --------------------------------------------------------
    async def _run_loop(self) -> None:
        while not self._stopping:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled error in bot loop tick — continuing")
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _tick(self) -> None:
        await self._roll_daily_window_if_needed()
        self._maybe_log_maker_fill_rate()
        state = await self.store.get_state()

        # 1. Always manage existing open positions, regardless of run state.
        open_positions = await self.store.get_open_positions()
        for position in open_positions:
            await self._manage_position(position)

        # 2. Compute equity and evaluate the kill switch.
        equity = await self._compute_equity()
        await self.store.record_equity(equity, equity - state.daily_start_equity)

        if not state.kill_switch:
            kill_reason = self.risk.check_daily_drawdown(equity, state.daily_start_equity)
            if kill_reason:
                await self.emergency_kill(kill_reason)
                return

        # 3. Look for new entries only if running and not killed.
        state = await self.store.get_state()  # refresh after possible kill
        if not state.running or state.kill_switch:
            return

        open_positions = await self.store.get_open_positions()
        if not self.risk.can_open_new_position(len(open_positions), state.kill_switch):
            return

        if state.throttle_paused_until and time.time() < state.throttle_paused_until:
            return  # consecutive-loss circuit breaker: sitting out the pause window

        open_symbols = {p.symbol for p in open_positions}
        for symbol in self.settings.symbols:
            if symbol in open_symbols:
                continue
            open_positions = await self.store.get_open_positions()
            if not self.risk.can_open_new_position(len(open_positions), state.kill_switch):
                break
            await self._evaluate_entry(symbol, equity)

    async def _roll_daily_window_if_needed(self) -> None:
        state = await self.store.get_state()
        # UTC explicitly — see the identical comment in futures_bot.py; the
        # daily loss limit is meant to lock until midnight UTC regardless of
        # where this happens to be deployed.
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        if state.daily_date != today:
            equity = await self._compute_equity()
            await self.store.update_state(
                daily_date=today, daily_start_equity=equity, kill_switch=False, kill_switch_reason="",
                consecutive_losses=0, throttle_paused_until=0.0, reduced_size_trades_remaining=0,
            )
            logger.info("New trading day started (UTC). Daily start equity=%.2f", equity)

    async def _compute_equity(self) -> float:
        quote_balance = await self.broker.get_quote_balance()
        open_positions = await self.store.get_open_positions()
        positions_value = 0.0
        for position in open_positions:
            try:
                price = await self.broker.get_price(position.symbol)
                self._last_prices[position.symbol] = price
                positions_value += price * position.qty
            except Exception:
                logger.warning("Could not fetch price for %s, using entry price", position.symbol)
                positions_value += position.entry_price * position.qty
        if self.settings.bot_mode == "paper":
            await self.store.update_state(paper_balance=quote_balance)
        return quote_balance + positions_value

    def _maybe_log_maker_fill_rate(self) -> None:
        """Once an hour, report what fraction of post-only entry attempts
        actually filled maker (vs timing out and getting walked away
        from) — the ratio PR30's chase-into-spread logic is meant to move.
        """
        now = time.time()
        if now - self._maker_fill_rate_logged_at < 3600:
            return
        if self._maker_entry_attempts > 0:
            rate = self._maker_entry_fills / self._maker_entry_attempts * 100
            logger.info(
                "MAKER_FILL_RATE %.1f%% (%d/%d) over the last hour",
                rate, self._maker_entry_fills, self._maker_entry_attempts,
            )
        self._maker_entry_attempts = 0
        self._maker_entry_fills = 0
        self._maker_fill_rate_logged_at = now

    def _check_taker_leakage(self, symbol: str, fill) -> None:
        """Entry fills should structurally never pay more than the maker
        rate — GTX/postOnly orders can only fill as maker or get rejected —
        so this alerting, not routine cost monitoring to size-throttle
        around. See RiskManager.is_taker_leakage for the full rationale."""
        notional = fill.price * fill.qty
        if self.risk.is_taker_leakage(fill.fee_quote, notional):
            fee_pct = (fill.fee_quote / notional * 100) if notional else 0.0
            logger.warning(
                "TAKER_LEAKAGE %s: fee=%.4f%% of notional (expected ~%.4f%% maker) on a fill that "
                "should have been maker-only — investigate order type/exchange fee schedule",
                symbol, fee_pct, self.settings.maker_fee_pct,
            )
            asyncio.create_task(
                self.notifier.send(
                    "Taker leakage detected",
                    f"{symbol} entry fill paid {fee_pct:.4f}% fee vs expected ~{self.settings.maker_fee_pct:.4f}% "
                    f"maker — a postOnly order should never fill as taker. Worth investigating.",
                    level="warning",
                )
            )

    def _log_skip(self, symbol: str, reason: str) -> None:
        """Log why a symbol didn't get an entry this tick — but only when
        the reason actually changes. Without the throttle this would log
        every symbol every poll_interval_seconds (every 5s by default),
        flooding the 500-entry log ring buffer and pushing out real
        OPENED/CLOSED lines within minutes."""
        if self._last_skip_reason.get(symbol) != reason:
            logger.info("SKIP %s: %s", symbol, reason)
            self._last_skip_reason[symbol] = reason

    async def _evaluate_entry(self, symbol: str, equity: float) -> None:
        try:
            df_1m = await self.broker.get_ohlcv(symbol, self.settings.timeframe, limit=100)
            df_htf = await self.broker.get_ohlcv(
                symbol, self.settings.htf_timeframe, limit=self.settings.htf_lookback_bars
            )
        except Exception:
            logger.exception("Failed to fetch OHLCV for %s", symbol)
            return

        df = attach_htf_bias(df_1m, df_htf, ema_period=self.settings.htf_ema_period)
        signal = self.strategy.generate_signal(df)
        # Spot is long-only by nature — you cannot sell an asset you do not
        # hold. Short signals are simply skipped here; the futures bot is
        # what acts on them.
        if signal.action != "long":
            reason = signal.reason if signal.action == "hold" else f"short signal not actionable on spot: {signal.reason}"
            self._log_skip(symbol, reason)
            return

        block_reason = await regime_block_reason(self.broker, symbol, "long", self.settings)
        if block_reason:
            self._log_skip(symbol, f"regime filter: {block_reason}")
            return

        sizing = self.risk.size_position(equity, signal.close, signal.atr, signal.atr_pct)
        if sizing is None or sizing.qty <= 0:
            logger.warning(
                "SIZE_ZERO %s: equity=%.2f risk_pct=%.2f%% entry=%.4f atr_pct=%.3f%% — sizing "
                "returned %s",
                symbol, equity, self.settings.max_risk_per_trade_pct, signal.close, signal.atr_pct,
                "None" if sizing is None else f"qty={sizing.qty:.6f}",
            )
            return

        state = await self.store.get_state()
        size_multiplier = self.risk.size_multiplier_for_streak(state.reduced_size_trades_remaining)
        qty = sizing.qty * size_multiplier

        self._maker_entry_attempts += 1
        try:
            fill = await self.broker.buy_post_only(symbol, qty, timeout_seconds=self.settings.post_only_timeout_seconds)
        except Exception:
            logger.exception("Buy order failed for %s", symbol)
            return

        if fill is None:
            logger.info(
                "POST_ONLY_GIVEUP %s: not filled after %d attempt(s) (%.0fs each), cancelled — "
                "will re-evaluate",
                symbol, self.settings.post_only_max_retries + 1, self.settings.post_only_timeout_seconds,
            )
            return

        self._maker_entry_fills += 1
        self._check_taker_leakage(symbol, fill)

        if size_multiplier < 1.0:
            await self.store.update_state(
                reduced_size_trades_remaining=max(0, state.reduced_size_trades_remaining - 1)
            )

        position = Position(
            symbol=symbol,
            side="long",
            status="open",
            entry_price=fill.price,
            qty=fill.qty,
            stop_loss_price=sizing.stop_loss_price,
            take_profit_price=sizing.take_profit_price,
            trailing_active=False,
            trailing_high=fill.price,
            opened_at=time.time(),
        )
        position = await self.store.open_position(position)
        await self.store.record_trade(
            Trade(
                position_id=position.id,
                symbol=symbol,
                side="buy",
                trade_type="entry",
                price=fill.price,
                qty=fill.qty,
                fee_quote=fill.fee_quote,
            )
        )
        logger.info(
            "OPENED %s qty=%.6f entry=%.4f SL=%.4f TP=%.4f size=%.0f%% (%s)",
            symbol,
            fill.qty,
            fill.price,
            sizing.stop_loss_price,
            sizing.take_profit_price,
            size_multiplier * 100,
            signal.reason,
        )

    async def _manage_position(self, position: Position) -> None:
        try:
            price = await self.broker.get_price(position.symbol)
        except Exception:
            logger.warning("Could not fetch price for open position %s", position.symbol)
            return
        self._last_prices[position.symbol] = price

        trailing_pct = self.settings.trailing_stop_pct / 100

        if price <= position.stop_loss_price:
            await self._close_position(position, position.stop_loss_price, "stop_loss")
            return

        # Trailing activates at trailing_activate_pct unrealized gain — a
        # smaller move than take_profit_pct itself; see the identical logic
        # (and rationale) in futures_bot.py._manage_position.
        activation_price = position.entry_price * (1 + self.settings.trailing_activate_pct / 100)
        if not position.trailing_active and price >= activation_price:
            new_high = max(position.trailing_high, price)
            await self.store.update_position(position.id, trailing_active=True, trailing_high=new_high)
            logger.info(
                "%s reached +%.2f%% trigger (%.4f) — trailing stop activated",
                position.symbol, self.settings.trailing_activate_pct, price,
            )
            return

        if position.trailing_active:
            new_high = max(position.trailing_high, price)
            trailing_stop_price = new_high * (1 - trailing_pct)
            if price <= trailing_stop_price:
                await self._close_position(position, trailing_stop_price, "trailing_stop")
                return
            if new_high != position.trailing_high:
                await self.store.update_position(position.id, trailing_high=new_high)

    async def _close_position(self, position: Position, expected_price: float, reason: str) -> None:
        """expected_price is the trigger level the exit was supposed to fill
        at (stop_loss_price, or the trailing level once trailing is active —
        see the two call sites in _manage_position); used below to detect
        excessive slippage on the actual fill."""
        try:
            fill = await self.broker.sell(position.symbol, position.qty)
        except Exception:
            logger.exception("Sell order failed for %s — will retry next tick", position.symbol)
            return

        cost_basis = position.entry_price * position.qty
        proceeds = fill.price * fill.qty - fill.fee_quote
        pnl_quote = proceeds - cost_basis
        pnl_pct = (pnl_quote / cost_basis * 100) if cost_basis else 0.0

        await self.store.close_position(position.id, fill.price, pnl_quote, pnl_pct, reason)
        await self.store.record_trade(
            Trade(
                position_id=position.id,
                symbol=position.symbol,
                side="sell",
                trade_type="exit",
                price=fill.price,
                qty=fill.qty,
                fee_quote=fill.fee_quote,
            )
        )
        logger.info(
            "CLOSED %s qty=%.6f exit=%.4f pnl=%.4f (%.2f%%) reason=%s",
            position.symbol,
            fill.qty,
            fill.price,
            pnl_quote,
            pnl_pct,
            reason,
        )

        # Only these two reasons have a real "expected price" to compare
        # against; a manual/kill close is an intentional market exit, not a
        # slippage event.
        if reason in ("stop_loss", "trailing_stop") and self.risk.is_slippage_excessive(
            fill.price, expected_price
        ):
            deviation_pct = abs(fill.price - expected_price) / expected_price * 100
            asyncio.create_task(
                self.notifier.send(
                    "Excessive slippage on close",
                    f"{position.symbol} {reason} expected {expected_price:.4f}, filled {fill.price:.4f} "
                    f"({deviation_pct:.2f}% away).",
                    level="warning",
                )
            )

        await self._record_trade_outcome(pnl_quote)

    async def _record_trade_outcome(self, pnl_quote: float) -> None:
        """Consecutive-loss circuit breaker — identical logic to
        futures_bot.py's version; see there for the full rationale."""
        state = await self.store.get_state()
        if pnl_quote > 0:
            if state.consecutive_losses:
                await self.store.update_state(consecutive_losses=0)
            return

        consecutive_losses = state.consecutive_losses + 1
        if self.risk.should_trigger_loss_throttle(consecutive_losses):
            pause_until = time.time() + self.settings.consecutive_loss_pause_minutes * 60
            await self.store.update_state(
                consecutive_losses=0,
                throttle_paused_until=pause_until,
                reduced_size_trades_remaining=self.settings.consecutive_loss_reduced_trades,
            )
            logger.warning(
                "Consecutive-loss circuit breaker: %s losses in a row — pausing new entries for "
                "%.0f minutes, then %s trades at %.0f%% size",
                self.settings.consecutive_loss_threshold, self.settings.consecutive_loss_pause_minutes,
                self.settings.consecutive_loss_reduced_trades,
                100 - self.settings.consecutive_loss_size_reduction_pct,
            )
            asyncio.create_task(
                self.notifier.send(
                    "Circuit breaker activated",
                    f"{self.settings.consecutive_loss_threshold} losses in a row — new entries paused for "
                    f"{self.settings.consecutive_loss_pause_minutes:.0f} min, then "
                    f"{self.settings.consecutive_loss_reduced_trades} trades at "
                    f"{100 - self.settings.consecutive_loss_size_reduction_pct:.0f}% size.",
                    level="critical",
                )
            )
        else:
            await self.store.update_state(consecutive_losses=consecutive_losses)
