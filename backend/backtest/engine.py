"""Event-driven futures backtest engine.

Deliberately does not reimplement signal generation or position sizing —
it imports and calls app.strategy.ScalpingStrategy and app.risk.RiskManager
exactly as app/futures_bot.py does, so a backtest run exercises the same
decision code that runs live. The only things this module owns are the
things a backtest genuinely has to do differently from a live poll loop:
walking historical bars in order, simulating intrabar stop/TP/trailing
touches from OHLC (a live bot polls a single current price; a backtest
only has high/low/close for each minute), and honest fee/slippage/funding
accounting.

Intrabar fill assumptions (stated up front because they're the main way a
backtest can lie to you):
  - Within one bar, a stop/trailing-stop touch is always resolved before a
    take-profit touch, even if both levels fall inside that bar's
    high-low range. This is the conservative assumption — it never lets a
    losing bar look like a winner because "the TP must have hit first".
  - A take-profit touch does not close the trade (matching production: it
    switches the position into trailing mode). The trailing stop is only
    checked starting the NEXT bar, not re-checked against the same bar's
    remaining range after activation. This is a known simplification: a
    sharp reversal inside the same 1-minute bar that would have re-crossed
    the new trailing level intrabar is not caught. Given the trailing
    width (0.3% default) versus typical 1-minute range, this is a rare
    edge case, not a systematic bias.
  - Fills use the exact fee/slippage formulas in app/exchange.py's
    PaperFuturesBroker, so a backtest run with simulate_funding=False
    (the default) is directly comparable to the live paper bot's own
    economics.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from app.config import Settings
from app.futures_bot import FuturesTradingBot, _directional_pnl
from app.risk import RiskManager
from app.strategy import ScalpingStrategy, _atr

SIGNAL_LOOKBACK_BARS = 100  # matches futures_bot._evaluate_entry's get_ohlcv(..., limit=100)
LEVERAGE_REFRESH_BARS = 5  # matches DYNAMIC_SYMBOL_REFRESH_SECONDS=300s at a 1m timeframe

# Perpetual futures funding settles every 8h on Binance USDT-M.
FUNDING_INTERVAL_BARS = 8 * 60


@dataclass
class BacktestPosition:
    symbol: str
    side: str
    qty: float
    entry_price: float
    leverage: float
    margin_used: float
    stop_loss_price: float
    take_profit_price: float
    trailing_active: bool = False
    trailing_high: float = 0.0
    opened_at: pd.Timestamp = None
    bars_held: int = 0


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    qty: float
    leverage: float
    pnl_quote: float
    pnl_pct: float
    fee_paid: float
    funding_paid: float
    reason: str
    opened_at: pd.Timestamp
    closed_at: pd.Timestamp
    bars_held: int


@dataclass
class BacktestResult:
    trades: List[ClosedTrade]
    equity_curve: List[tuple]  # (timestamp, equity)
    ending_balance: float
    kill_switch_events: List[tuple]  # (timestamp, reason)


def _simulate_fee_and_slippage(settings: Settings, price: float, side: str) -> float:
    """Identical to PaperFuturesBroker._simulate_fee_and_slippage."""
    slip = settings.slippage_buffer_pct / 100
    return price * (1 + slip) if side == "buy" else price * (1 - slip)


class BacktestEngine:
    def __init__(
        self,
        settings: Settings,
        data: Dict[str, pd.DataFrame],
        leverage_mode: str = "auto",
        fixed_leverage: Optional[float] = None,
        simulate_funding: bool = False,
        funding_rate_pct_per_interval: float = 0.01,
    ):
        """
        data: symbol -> DataFrame with columns [timestamp, open, high, low, close, volume],
              sorted ascending, one entry per symbol traded.
        leverage_mode: "auto" reproduces futures_bot's ATR-driven ceiling (using the first
              symbol in `data` as the BTC proxy, same as production always keying auto
              leverage off BTC/USDT:USDT regardless of what's actually traded). "fixed" uses
              fixed_leverage for every entry.
        simulate_funding: off by default to match PaperFuturesBroker (which does not model
              funding) — flip on to see the cost impact of holding leveraged futures
              positions, since that omission is a known gap in the live paper bot too.
        """
        self.settings = settings
        self.strategy = ScalpingStrategy()
        self.risk = RiskManager(settings)
        self.data = data
        self.leverage_mode = leverage_mode
        self.fixed_leverage = fixed_leverage or settings.futures_leverage_default
        self.simulate_funding = simulate_funding
        self.funding_rate_pct_per_interval = funding_rate_pct_per_interval

        self._leverage_bot = FuturesTradingBot.__new__(FuturesTradingBot)
        self._leverage_bot.settings = settings

        self.balance = settings.futures_paper_starting_balance
        self.positions: Dict[str, BacktestPosition] = {}
        self.trades: List[ClosedTrade] = []
        self.equity_curve: List[tuple] = []
        self.kill_switch_events: List[tuple] = []

        self.daily_start_equity = self.balance
        self.daily_date: Optional[dt.date] = None
        self.kill_switch = False

        self._current_leverage_ceiling = settings.futures_auto_leverage_max
        self._leverage_bar_counter = 0

    # ---- Public entry point ------------------------------------------------
    def run(self) -> BacktestResult:
        timeline = sorted(set().union(*(set(df["timestamp"]) for df in self.data.values())))
        indexed = {sym: df.set_index("timestamp") for sym, df in self.data.items()}

        for i, ts in enumerate(timeline):
            self._on_bar(ts, i, indexed)

        # Force-close anything still open at the end so P&L is never left dangling.
        for symbol in list(self.positions):
            last_row = indexed[symbol].iloc[-1]
            self._close_position(symbol, float(last_row["close"]), "backtest_end", timeline[-1])

        return BacktestResult(
            trades=self.trades,
            equity_curve=self.equity_curve,
            ending_balance=self.balance,
            kill_switch_events=self.kill_switch_events,
        )

    # ---- Per-bar tick, mirrors FuturesTradingBot._tick ----------------------
    def _on_bar(self, ts: pd.Timestamp, i: int, indexed: Dict[str, pd.DataFrame]) -> None:
        self._roll_daily_window_if_needed(ts)

        for symbol in list(self.positions):
            if ts not in indexed[symbol].index:
                continue
            bar = indexed[symbol].loc[ts]
            self._manage_position_bar(symbol, bar, ts)

        equity = self._compute_equity(ts, indexed)
        self.equity_curve.append((ts, equity))

        if not self.kill_switch:
            kill_reason = self.risk.check_daily_drawdown(equity, self.daily_start_equity)
            if kill_reason:
                self._emergency_kill(kill_reason, ts, indexed)
                return

        if self.kill_switch:
            return

        self._maybe_refresh_auto_leverage(ts, indexed, i)

        if not self.risk.can_open_new_position(len(self.positions), self.kill_switch):
            return

        for symbol, df in indexed.items():
            if symbol in self.positions:
                continue
            if ts not in df.index:
                continue
            pos_index = df.index.get_loc(ts)
            if isinstance(pos_index, slice):  # duplicate timestamps, shouldn't happen post-dedupe
                continue
            if pos_index + 1 < SIGNAL_LOOKBACK_BARS:
                continue  # not enough warmup history yet, matches strategy.MIN_CANDLES gate loosely
            if not self.risk.can_open_new_position(len(self.positions), self.kill_switch):
                break
            window = df.iloc[max(0, pos_index - SIGNAL_LOOKBACK_BARS + 1): pos_index + 1]
            self._evaluate_entry(symbol, window, equity, ts)

    # ---- Daily window / kill switch, mirrors futures_bot ---------------------
    def _roll_daily_window_if_needed(self, ts: pd.Timestamp) -> None:
        today = ts.date()
        if self.daily_date != today:
            equity = self.balance + sum(p.margin_used for p in self.positions.values())
            self.daily_start_equity = equity
            self.daily_date = today
            self.kill_switch = False

    def _compute_equity(self, ts: pd.Timestamp, indexed: Dict[str, pd.DataFrame]) -> float:
        positions_equity = 0.0
        for symbol, position in self.positions.items():
            if ts in indexed[symbol].index:
                price = float(indexed[symbol].loc[ts]["close"])
            else:
                price = position.entry_price
            unrealized = _directional_pnl(position.side, position.entry_price, price, position.qty)
            positions_equity += position.margin_used + unrealized
        return self.balance + positions_equity

    def _emergency_kill(self, reason: str, ts: pd.Timestamp, indexed: Dict[str, pd.DataFrame]) -> None:
        self.kill_switch = True
        self.kill_switch_events.append((ts, reason))
        for symbol in list(self.positions):
            price = float(indexed[symbol].loc[ts]["close"]) if ts in indexed[symbol].index else self.positions[symbol].entry_price
            self._close_position(symbol, price, "emergency_kill", ts)

    # ---- Auto leverage, mirrors futures_bot._maybe_refresh_auto_leverage -----
    def _maybe_refresh_auto_leverage(self, ts: pd.Timestamp, indexed: Dict[str, pd.DataFrame], i: int) -> None:
        if self.leverage_mode != "auto":
            return
        self._leverage_bar_counter += 1
        if self._leverage_bar_counter < LEVERAGE_REFRESH_BARS and self.equity_curve:
            return
        self._leverage_bar_counter = 0

        proxy_symbol = next(iter(indexed))  # first traded symbol stands in for the BTC ATR proxy
        df = indexed[proxy_symbol]
        if ts not in df.index:
            return
        pos_index = df.index.get_loc(ts)
        if isinstance(pos_index, slice) or pos_index < 14:
            return
        window = df.iloc[max(0, pos_index - 29): pos_index + 1].reset_index()
        last_close = float(window["close"].iloc[-1])
        last_atr = float(_atr(window, 14).iloc[-1])
        atr_pct = (last_atr / last_close * 100) if last_close else 0.0
        self._current_leverage_ceiling = round(
            self._leverage_bot._map_atr_to_leverage_ceiling(atr_pct), 1
        )

    def _requested_leverage(self) -> float:
        return self._current_leverage_ceiling if self.leverage_mode == "auto" else self.fixed_leverage

    # ---- Entries, mirrors futures_bot._evaluate_entry ------------------------
    def _evaluate_entry(self, symbol: str, window: pd.DataFrame, equity: float, ts: pd.Timestamp) -> None:
        signal = self.strategy.generate_signal(window)
        if signal.action not in ("long", "short"):
            return
        side = signal.action

        sizing = self.risk.size_position_leveraged(
            equity, signal.close, signal.atr, signal.atr_pct,
            self._requested_leverage(), self.settings.futures_max_leverage, side=side,
        )
        if sizing is None or sizing.qty <= 0:
            return

        mark = float(window["close"].iloc[-1])
        fill_price = _simulate_fee_and_slippage(self.settings, mark, "sell" if side == "short" else "buy")
        notional = fill_price * sizing.qty
        margin_required = notional / sizing.leverage
        fee = notional * (self.settings.taker_fee_pct / 100)
        if margin_required + fee > self.balance:
            return

        self.balance -= margin_required + fee
        self.positions[symbol] = BacktestPosition(
            symbol=symbol,
            side=side,
            qty=sizing.qty,
            entry_price=fill_price,
            leverage=sizing.leverage,
            margin_used=margin_required,
            stop_loss_price=sizing.stop_loss_price,
            take_profit_price=sizing.take_profit_price,
            trailing_active=False,
            trailing_high=fill_price,
            opened_at=ts,
            bars_held=0,
        )
        self._entry_fee = getattr(self, "_entry_fee", {})
        self._entry_fee[symbol] = fee

    # ---- Position management, mirrors futures_bot._manage_position -----------
    def _manage_position_bar(self, symbol: str, bar: pd.Series, ts: pd.Timestamp) -> None:
        position = self.positions[symbol]
        position.bars_held += 1
        high, low = float(bar["high"]), float(bar["low"])
        is_short = position.side == "short"
        trailing_pct = self.settings.trailing_stop_pct / 100

        stop_touched = high >= position.stop_loss_price if is_short else low <= position.stop_loss_price
        if stop_touched:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            self._close_position(symbol, position.stop_loss_price, reason, ts)
            return

        if not position.trailing_active:
            tp_touched = low <= position.take_profit_price if is_short else high >= position.take_profit_price
            if tp_touched:
                new_mark = low if is_short else high
                trailing_stop_price = new_mark * (1 + trailing_pct) if is_short else new_mark * (1 - trailing_pct)
                position.trailing_active = True
                position.trailing_high = new_mark
                position.stop_loss_price = trailing_stop_price
                return

        if position.trailing_active:
            candidate = min(position.trailing_high, low) if is_short else max(position.trailing_high, high)
            new_trailing_stop = candidate * (1 + trailing_pct) if is_short else candidate * (1 - trailing_pct)
            improved = (
                candidate < position.trailing_high and new_trailing_stop < position.stop_loss_price
                if is_short
                else candidate > position.trailing_high and new_trailing_stop > position.stop_loss_price
            )
            if improved:
                position.trailing_high = candidate
                position.stop_loss_price = new_trailing_stop

    # ---- Exits ---------------------------------------------------------------
    def _close_position(self, symbol: str, trigger_price: float, reason: str, ts: pd.Timestamp) -> None:
        position = self.positions.pop(symbol)
        fill_price = _simulate_fee_and_slippage(
            self.settings, trigger_price, "buy" if position.side == "short" else "sell"
        )
        entry_notional = position.entry_price * position.qty
        exit_notional = fill_price * position.qty
        leveraged_pnl = (
            entry_notional - exit_notional if position.side == "short" else exit_notional - entry_notional
        )
        exit_fee = exit_notional * (self.settings.taker_fee_pct / 100)

        funding_paid = 0.0
        if self.simulate_funding:
            funding_paid = self._accrue_funding(position, entry_notional)

        pnl_quote = leveraged_pnl - exit_fee - funding_paid
        pnl_pct = (pnl_quote / position.margin_used * 100) if position.margin_used else 0.0

        self.balance += position.margin_used + leveraged_pnl - exit_fee - funding_paid

        entry_fee = getattr(self, "_entry_fee", {}).pop(symbol, 0.0)
        self.trades.append(
            ClosedTrade(
                symbol=symbol,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=fill_price,
                qty=position.qty,
                leverage=position.leverage,
                pnl_quote=pnl_quote,
                pnl_pct=pnl_pct,
                fee_paid=entry_fee + exit_fee,
                funding_paid=funding_paid,
                reason=reason,
                opened_at=position.opened_at,
                closed_at=ts,
                bars_held=position.bars_held,
            )
        )

    def _accrue_funding(self, position: BacktestPosition, entry_notional: float) -> float:
        """Rough funding cost: one interval's worth of the configured rate for
        every FUNDING_INTERVAL_BARS the position was held, applied to notional.
        Longs pay positive funding (the typical sign in a bull perpetual
        market); shorts receive it — sign flips accordingly, same convention
        Binance uses.
        """
        intervals = position.bars_held // FUNDING_INTERVAL_BARS
        if intervals <= 0:
            return 0.0
        rate = self.funding_rate_pct_per_interval / 100
        cost = entry_notional * rate * intervals
        return cost if position.side == "long" else -cost
