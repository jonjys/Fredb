"""Scalping strategy: EMA crossover + RSI filter + Bollinger Band context.

Long-only (spot trading has no native short side). Designed for short
timeframes (1m) with frequent, small, high-probability entries rather than
chasing big moves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

Action = Literal["long", "short", "hold"]


@dataclass
class Signal:
    action: Action
    reason: str
    atr: float
    atr_pct: float
    close: float


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # avg_loss == 0 makes rs undefined, and the two cases behind it mean
    # opposite things: gains with zero losses is a maximally overbought
    # market (100), while no movement at all is neutral (50). Collapsing
    # both to a neutral fill would make the overbought guard read 50 during
    # exactly the vertical, no-pullback moves it exists to filter out.
    rsi = rsi.where(avg_loss > 0, np.where(avg_gain > 0, 100.0, 50.0))
    return rsi.fillna(50)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return lower, mid, upper


MIN_CANDLES = 30


class ScalpingStrategy:
    """Fast EMA/RSI momentum scalper with a Bollinger Band overextension filter.

    Generates entries in both directions. The short side is a deliberate
    mirror of the long side rather than a separate ruleset — same crossover,
    same RSI band reflected around 50, same "don't chase a move that already
    ran into the band" guard. Keeping them symmetric means the strategy has
    no structural bias toward one direction, which matters: a long-only
    momentum bot in a downtrend either sits idle or keeps buying failed
    bounces.

    Only futures can actually act on a short (you cannot sell spot you do
    not hold), so the spot bot ignores short signals — see bot.py.
    """

    def __init__(
        self,
        ema_fast: int = 9,
        ema_slow: int = 21,
        rsi_period: int = 14,
        rsi_min: float = 45.0,
        rsi_max: float = 70.0,
        atr_period: int = 14,
        bb_period: int = 20,
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.rsi_min = rsi_min
        self.rsi_max = rsi_max
        self.atr_period = atr_period
        self.bb_period = bb_period

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < MIN_CANDLES:
            close = float(df["close"].iloc[-1]) if len(df) else 0.0
            return Signal("hold", "not enough candles", 0.0, 0.0, close)

        close = df["close"]
        ema_fast = _ema(close, self.ema_fast)
        ema_slow = _ema(close, self.ema_slow)
        rsi = _rsi(close, self.rsi_period)
        atr = _atr(df, self.atr_period)
        lower_bb, mid_bb, upper_bb = _bollinger(close, self.bb_period)

        last_close = float(close.iloc[-1])
        last_atr = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0
        atr_pct = (last_atr / last_close * 100) if last_close else 0.0

        prev_fast, prev_slow = float(ema_fast.iloc[-2]), float(ema_slow.iloc[-2])
        cur_fast, cur_slow = float(ema_fast.iloc[-1]), float(ema_slow.iloc[-1])
        cur_rsi = float(rsi.iloc[-1])
        cur_upper_bb = float(upper_bb.iloc[-1]) if not np.isnan(upper_bb.iloc[-1]) else None
        cur_lower_bb = float(lower_bb.iloc[-1]) if not np.isnan(lower_bb.iloc[-1]) else None

        # --- Long side --------------------------------------------------
        bullish_cross = prev_fast <= prev_slow and cur_fast > cur_slow
        trend_up = cur_fast > cur_slow and last_close > cur_fast
        rsi_ok_long = self.rsi_min <= cur_rsi <= self.rsi_max
        not_overextended_up = cur_upper_bb is None or last_close < cur_upper_bb

        if (bullish_cross or trend_up) and rsi_ok_long and not_overextended_up:
            reason = f"EMA{self.ema_fast}>{self.ema_slow}, RSI={cur_rsi:.1f}"
            return Signal("long", reason, last_atr, atr_pct, last_close)

        # --- Short side (mirror of the above) ----------------------------
        # RSI band reflected around 50: a [45, 70] long band becomes
        # [30, 55] for shorts, so "healthy momentum, not yet exhausted"
        # means the same thing in both directions.
        bearish_cross = prev_fast >= prev_slow and cur_fast < cur_slow
        trend_down = cur_fast < cur_slow and last_close < cur_fast
        rsi_ok_short = (100 - self.rsi_max) <= cur_rsi <= (100 - self.rsi_min)
        not_overextended_down = cur_lower_bb is None or last_close > cur_lower_bb

        if (bearish_cross or trend_down) and rsi_ok_short and not_overextended_down:
            reason = f"EMA{self.ema_fast}<{self.ema_slow}, RSI={cur_rsi:.1f}"
            return Signal("short", reason, last_atr, atr_pct, last_close)

        return Signal("hold", "no edge", last_atr, atr_pct, last_close)
