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
        qty_by_risk = risk_amount / (entry_price * stop_distance_pct)

        max_notional_per_position = equity / max(1, self.settings.max_concurrent_positions)
        qty_by_allocation = max_notional_per_position / entry_price

        qty = min(qty_by_risk, qty_by_allocation)
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

    # ---- Fees / slippage --------------------------------------------------
    def round_trip_cost_pct(self) -> float:
        """Approximate cost of entering and exiting a position, for sanity checks."""
        return 2 * self.settings.taker_fee_pct + 2 * self.settings.slippage_buffer_pct

    def is_take_profit_worth_it(self) -> bool:
        """Guards against configuring a TP smaller than round-trip costs."""
        return self.settings.take_profit_pct > self.round_trip_cost_pct()
