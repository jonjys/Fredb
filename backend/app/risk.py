# app/risk.py
"""Risk management: position sizing, exposure limits, and the daily kill-switch.

This module is the most important piece of the bot. Every entry must pass
through here before an order is placed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.config import Settings

logger = logging.getLogger("tradingbot.risk")

MIN_STOP_PCT = 0.15  # never risk less than this distance; avoids noise stop-outs


@dataclass
class SizingResult:
    qty: float
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    risk_amount_quote: float


@dataclass
class FuturesSizingResult(SizingResult):
    leverage: float
    margin_required_quote: float
    liquidation_price: float


# Conservative flat estimate of Binance USDT-M maintenance margin rate at
# moderate notional (actual rate is tiered and gets worse at high notional —
# this is deliberately pessimistic so the safety clamp below stays safe).
MAINTENANCE_MARGIN_RATE_ESTIMATE = 0.005

# Our stop-loss must trigger within this fraction of the estimated
# liquidation distance, not right at it — leaves a buffer for slippage,
# funding drift, and poll-interval latency on the trailing-stop leg.
LEVERAGE_SAFETY_FACTOR = 0.7


class RiskManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ---- Position sizing --------------------------------------------------
    def size_position(
        self, equity: float, entry_price: float, atr: float, atr_pct: float
    ) -> Optional[SizingResult]:
        """Volatility-adjusted position sizing.

        risk_amount = equity * risk_pct
        stop_distance_pct = max(ATR% * multiplier, MIN_STOP_PCT, configured stop_loss_pct)
        qty = risk_amount / (entry_price * stop_distance_pct)

        Also caps notional so no single position exceeds an equal share of
        equity across the configured max concurrent positions.
        """
        if entry_price <= 0 or equity <= 0:
            return None

        stop_distance_pct = max(
            atr_pct * self.settings.atr_multiplier,
            self.settings.stop_loss_pct,
            MIN_STOP_PCT,
        ) / 100

        risk_amount = equity * (self.settings.max_risk_per_trade_pct / 100)
        # Volatility throttle: the wider stop from atr_pct*atr_multiplier
        # above already shrinks qty on a volatile bar, but not the dollar
        # risk itself — a news-spike bar can still land a full risk_pct bet
        # on a stop that's about to be tested immediately. Cut risk_amount
        # itself once ATR% crosses into unusually-volatile territory.
        if atr_pct > self.settings.high_volatility_atr_pct:
            risk_amount *= self.settings.high_volatility_risk_multiplier
        qty_by_risk = risk_amount / (entry_price * stop_distance_pct)

        max_notional_per_position = equity / max(1, self.settings.max_concurrent_positions)
        qty_by_allocation = max_notional_per_position / entry_price

        # Hard notional ceiling, independent of the risk-based qty above —
        # a backstop against tail/gap risk the modeled stop can't react to
        # (an exchange outage, a flash crash), not another risk-per-trade
        # control layered on the same thing.
        qty_by_notional_cap = (equity * self.settings.max_notional_pct_of_equity) / entry_price

        qty = min(qty_by_risk, qty_by_allocation, qty_by_notional_cap)
        if qty <= 0:
            return None

        stop_loss_price = entry_price * (1 - stop_distance_pct)
        take_profit_price = entry_price * (1 + self.settings.take_profit_pct / 100)

        return SizingResult(
            qty=qty,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            risk_amount_quote=risk_amount,
        )

    # ---- Exposure limits ----------------------------------------------------
    def can_open_new_position(self, open_positions_count: int, kill_switch_active: bool) -> bool:
        if kill_switch_active:
            return False
        return open_positions_count < self.settings.max_concurrent_positions

    # ---- Daily kill-switch --------------------------------------------------
    def check_daily_drawdown(self, equity: float, daily_start_equity: float) -> Optional[str]:
        """Returns a reason string if the daily loss limit has been breached."""
        if daily_start_equity <= 0:
            return None
        drawdown_pct = (daily_start_equity - equity) / daily_start_equity * 100
        if drawdown_pct >= self.settings.max_daily_loss_pct:
            return (
                f"Daily drawdown {drawdown_pct:.2f}% >= limit "
                f"{self.settings.max_daily_loss_pct:.2f}% — trading halted for today"
            )
        return None

    # ---- Leverage (futures) --------------------------------------------------
    def max_safe_leverage(
        self,
        stop_distance_pct: float,
        maintenance_margin_rate: float = MAINTENANCE_MARGIN_RATE_ESTIMATE,
        safety_factor: float = LEVERAGE_SAFETY_FACTOR,
    ) -> float:
        """The highest leverage at which our stop-loss still triggers safely
        before the exchange's own liquidation engine would close the position.

        Liquidation happens (approximately, ignoring funding/fees) once losses
        eat through the margin down to the maintenance margin threshold:
            liq_distance_pct ~= 1/leverage - maintenance_margin_rate
        We require stop_distance_pct <= safety_factor * liq_distance_pct, i.e.
        our stop must fire well inside that distance. Solving for leverage:
            leverage <= safety_factor / (stop_distance_pct + safety_factor * mmr)
        """
        stop_distance = stop_distance_pct / 100
        denom = stop_distance + safety_factor * maintenance_margin_rate
        if denom <= 0:
            return 1.0
        return max(1.0, safety_factor / denom)

    def size_position_leveraged(
        self,
        equity: float,
        entry_price: float,
        atr: float,
        atr_pct: float,
        requested_leverage: float,
        max_leverage_cap: float,
        side: str = "long",
    ) -> Optional[FuturesSizingResult]:
        """Same $-risk-based qty as spot (leverage does not change how much
        you risk per trade) — leverage only changes margin efficiency. The
        requested leverage is clamped down, never up, by both the
        liquidation-safety check and the configured hard cap.

        For a short everything price-directional flips: the stop sits ABOVE
        entry, the take-profit BELOW, and liquidation is ABOVE (a short is
        liquidated when price rises against it). Distances are identical to
        the long case, so risk-per-trade and the leverage-safety margin are
        symmetric between the two directions.
        """
        base = self.size_position(equity, entry_price, atr, atr_pct)
        if base is None:
            return None

        stop_distance_pct = abs(entry_price - base.stop_loss_price) / entry_price * 100
        safe_max_leverage = self.max_safe_leverage(stop_distance_pct)
        leverage = min(requested_leverage, safe_max_leverage, max_leverage_cap)
        leverage = max(1.0, round(leverage, 2))

        notional = base.qty * entry_price
        margin_required = notional / leverage

        stop_distance = stop_distance_pct / 100
        take_profit_distance = self.settings.take_profit_pct / 100
        liq_distance = (1 / leverage) - MAINTENANCE_MARGIN_RATE_ESTIMATE

        if side == "short":
            stop_loss_price = entry_price * (1 + stop_distance)
            take_profit_price = entry_price * (1 - take_profit_distance)
            liquidation_price = entry_price * (1 + liq_distance)
        else:
            stop_loss_price = entry_price * (1 - stop_distance)
            take_profit_price = entry_price * (1 + take_profit_distance)
            liquidation_price = entry_price * (1 - liq_distance)

        return FuturesSizingResult(
            qty=base.qty,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            risk_amount_quote=base.risk_amount_quote,
            leverage=leverage,
            margin_required_quote=margin_required,
            liquidation_price=liquidation_price,
        )

    # ---- Fees / slippage --------------------------------------------------
    def round_trip_cost_pct(self) -> float:
        """Approximate cost of entering and exiting a position, for sanity checks.

        Entries are always postOnly/GTX (maker fee, no modeled slippage —
        see PaperBroker/PaperFuturesBroker.buy_post_only, which fills
        exactly at the quoted touch price). Exits (stop-loss, trailing
        stop, take-profit) are market/taker orders, which do slip. This
        used to charge 2x taker_fee_pct + 2x slippage_buffer_pct — treating
        both legs as taker — which overstated the real floor and, combined
        with a too-tight take_profit_pct, is what silently broke the
        cost-floor guard's usefulness before it was ever wired in.
        """
        return self.settings.maker_fee_pct + self.settings.taker_fee_pct + self.settings.slippage_buffer_pct

    def is_take_profit_worth_it(self) -> bool:
        """Guards against configuring a TP that barely clears round-trip costs.

        A margin of just over 1x cost survives fees on paper but not the
        first bit of real slippage or an unfavorable fill — the multiplier
        is a deliberate floor, not just a > 0 check.
        """
        return self.settings.take_profit_pct >= self.round_trip_cost_pct() * self.settings.min_tp_cost_multiple

    # ---- Consecutive-loss circuit breaker ----------------------------------
    def should_trigger_loss_throttle(self, consecutive_losses: int) -> bool:
        """True the moment the losing streak reaches the configured threshold
        (default 4). The caller (bot loop) is responsible for firing this
        exactly once per streak — see FuturesBotState.throttle_armed."""
        return consecutive_losses >= self.settings.consecutive_loss_threshold

    def size_multiplier_for_streak(self, reduced_size_trades_remaining: int) -> float:
        """0.5x while inside the post-pause reduced-size window, else 1x.
        Purely a function of state the bot loop already tracks (how many of
        the post-throttle trades are left) — no side effects here."""
        reduction = self.settings.consecutive_loss_size_reduction_pct / 100
        return (1.0 - reduction) if reduced_size_trades_remaining > 0 else 1.0

    # ---- Execution-quality alerting -----------------------------------------
    def is_taker_leakage(self, fee_quote: float, notional: float) -> bool:
        """True when an entry fill's realized fee rate exceeds the expected
        maker rate by more than taker_leakage_fee_multiple. This should
        structurally never happen — GTX/postOnly orders can only fill as
        maker or get rejected outright by the exchange — so seeing it at
        all points at something upstream (a fee-schedule change, an order
        type regression), not routine cost drift to size-throttle around.
        """
        if notional <= 0:
            return False
        fee_pct = fee_quote / notional * 100
        return fee_pct > self.settings.maker_fee_pct * self.settings.taker_leakage_fee_multiple

    # ---- Slippage alerting --------------------------------------------------
    def is_slippage_excessive(self, fill_price: float, expected_price: float) -> bool:
        """True when a stop/trailing-stop fill landed further from the level
        it was supposed to trigger at than settings.slippage_alert_pct — the
        threshold for "this is worth waking someone up about" rather than
        just the normal, small, already-priced-in slippage_buffer_pct.
        """
        if expected_price <= 0:
            return False
        deviation_pct = abs(fill_price - expected_price) / expected_price * 100
        return deviation_pct >= self.settings.slippage_alert_pct
