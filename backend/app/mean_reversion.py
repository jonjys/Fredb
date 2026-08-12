"""Multi-timeframe mean-reversion strategy: fade extension into the Bollinger
Bands on the entry (1m) timeframe, only in the direction the higher
timeframe (15m) isn't actively fighting.

Deliberately reuses app.strategy's indicator primitives (_ema/_rsi/_atr/
_bollinger) and its Signal dataclass rather than re-deriving them — the
entry *rule* is new, the math underneath it isn't, and every consumer
(bot.py, futures_bot.py, risk.py, the backtest engine) already knows how
to read a Signal.

This is explicitly a counter-trend strategy, so it has the mirror-image
failure mode of the trend-following EMA-cross strategy it replaces: instead
of buying pullbacks in a strong uptrend and getting run over on reversals,
it fades extensions and can get run over by a strong impulse that keeps
extending. The HTF bias gate below is the mitigation, not a guarantee —
validate with backend/backtest/ before trusting it live, same as any other
strategy change in this codebase.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from app.strategy import Signal, _atr, _bollinger, _ema, _rsi

HtfBias = Literal["bullish", "bearish", "neutral"]

MR_MIN_CANDLES = 30


def compute_htf_bias(df_htf: pd.DataFrame, ema_period: int = 50, slope_lookback: int = 20) -> pd.Series:
    """Per-bar HTF regime label for every row of a higher-timeframe (e.g. 15m)
    OHLCV frame: "bullish" (EMA rising and price above it), "bearish" (EMA
    falling and price below it), else "neutral". Vectorized so it can be
    computed once per HTF frame, not recomputed per 1m bar.
    """
    close = df_htf["close"]
    ema = _ema(close, ema_period)
    ema_prior = ema.shift(slope_lookback)
    rising = ema > ema_prior
    falling = ema < ema_prior
    bullish = rising & (close > ema)
    bearish = falling & (close < ema)
    bias = pd.Series("neutral", index=df_htf.index, dtype=object)
    bias = bias.mask(bullish, "bullish")
    bias = bias.mask(bearish, "bearish")
    return bias


def attach_htf_bias(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, ema_period: int = 50) -> pd.DataFrame:
    """Return a copy of the 1m frame with an 'htf_bias' column, aligning each
    1m bar to the most recently *closed* HTF bar at or before it.

    Uses merge_asof (backward) specifically to avoid lookahead: a 1m bar at
    14:07 must only ever see the 15m bar that closed at 14:00, never the one
    still forming at 14:15. Both frames must be sorted by timestamp and use
    the same column name/dtype for the join key.
    """
    if "timestamp" not in df_ltf.columns or "timestamp" not in df_htf.columns:
        raise ValueError("attach_htf_bias requires a 'timestamp' column on both frames")

    htf = df_htf.copy()
    htf["htf_bias"] = compute_htf_bias(htf, ema_period=ema_period)
    ltf_sorted = df_ltf.sort_values("timestamp")
    htf_sorted = htf[["timestamp", "htf_bias"]].sort_values("timestamp")
    merged = pd.merge_asof(ltf_sorted, htf_sorted, on="timestamp", direction="backward")
    merged["htf_bias"] = merged["htf_bias"].fillna("neutral")
    return merged


@dataclass
class MeanReversionStrategy:
    """Long: 1m close at/through the lower band, RSI oversold, volume above
    its own 20-bar average, extension >= min_distance_std from the midband,
    and the 15m regime not outright bearish. Short is the exact mirror.
    """

    bb_period: int = 20
    bb_std: float = 2.2
    rsi_period: int = 14
    rsi_oversold: float = 28.0
    rsi_overbought: float = 72.0
    volume_sma_period: int = 20
    min_distance_std: float = 1.1
    atr_period: int = 14

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        min_len = max(MR_MIN_CANDLES, self.bb_period + 1, self.volume_sma_period + 1)
        if len(df) < min_len:
            close = float(df["close"].iloc[-1]) if len(df) else 0.0
            return Signal("hold", "not enough candles", 0.0, 0.0, close)

        close = df["close"]
        volume = df["volume"]
        lower_bb, mid_bb, upper_bb = _bollinger(close, self.bb_period, self.bb_std)
        rsi = _rsi(close, self.rsi_period)
        atr = _atr(df, self.atr_period)
        vol_sma = volume.rolling(self.volume_sma_period).mean()

        last_close = float(close.iloc[-1])
        last_rsi = float(rsi.iloc[-1])
        last_lower = float(lower_bb.iloc[-1]) if not np.isnan(lower_bb.iloc[-1]) else None
        last_upper = float(upper_bb.iloc[-1]) if not np.isnan(upper_bb.iloc[-1]) else None
        last_mid = float(mid_bb.iloc[-1]) if not np.isnan(mid_bb.iloc[-1]) else None
        last_atr = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0
        atr_pct = (last_atr / last_close * 100) if last_close else 0.0
        last_vol = float(volume.iloc[-1])
        last_vol_sma = float(vol_sma.iloc[-1]) if not np.isnan(vol_sma.iloc[-1]) else 0.0

        if last_lower is None or last_upper is None or last_mid is None:
            return Signal("hold", "bollinger bands not warmed up", last_atr, atr_pct, last_close)

        # band half-width in raw std units (bb_std multiples cancel out)
        band_half_width_std = (last_upper - last_mid) / self.bb_std if self.bb_std else 0.0
        distance_std = abs(last_close - last_mid) / band_half_width_std if band_half_width_std else 0.0

        htf_bias: HtfBias = df["htf_bias"].iloc[-1] if "htf_bias" in df.columns else "neutral"

        volume_ok = last_vol_sma > 0 and last_vol > last_vol_sma
        distance_ok = distance_std >= self.min_distance_std

        long_ok = (
            last_close <= last_lower
            and last_rsi < self.rsi_oversold
            and volume_ok
            and distance_ok
            and htf_bias != "bearish"
        )
        if long_ok:
            reason = (
                f"BB lower touch, RSI={last_rsi:.1f}, dist={distance_std:.2f}σ, "
                f"vol={last_vol / last_vol_sma:.2f}x avg, HTF={htf_bias}"
            )
            return Signal("long", reason, last_atr, atr_pct, last_close)

        short_ok = (
            last_close >= last_upper
            and last_rsi > self.rsi_overbought
            and volume_ok
            and distance_ok
            and htf_bias != "bullish"
        )
        if short_ok:
            reason = (
                f"BB upper touch, RSI={last_rsi:.1f}, dist={distance_std:.2f}σ, "
                f"vol={last_vol / last_vol_sma:.2f}x avg, HTF={htf_bias}"
            )
            return Signal("short", reason, last_atr, atr_pct, last_close)

        return Signal(
            "hold",
            self._skip_reason(
                last_close, last_lower, last_upper, last_rsi, volume_ok, distance_ok,
                distance_std, htf_bias, last_vol, last_vol_sma,
            ),
            last_atr, atr_pct, last_close,
        )

    def _skip_reason(
        self,
        last_close: float,
        last_lower: float,
        last_upper: float,
        last_rsi: float,
        volume_ok: bool,
        distance_ok: bool,
        distance_std: float,
        htf_bias: HtfBias,
        last_vol: float,
        last_vol_sma: float,
    ) -> str:
        """Which specific gate blocked entry this bar, for the closer of the
        two bands (there's no meaningful "why not long" story on a bar that
        isn't even near the lower band). Reported per-symbol by the caller,
        throttled to only log when the reason actually changes — see
        bot.py/futures_bot.py._evaluate_entry.
        """
        touching_lower = last_close <= last_lower
        touching_upper = last_close >= last_upper
        if not touching_lower and not touching_upper:
            return f"no band touch (close={last_close:.4f}, bands=[{last_lower:.4f},{last_upper:.4f}])"

        side, rsi_gate, rsi_threshold, htf_block = (
            ("long", last_rsi >= self.rsi_oversold, self.rsi_oversold, "bearish")
            if touching_lower
            else ("short", last_rsi <= self.rsi_overbought, self.rsi_overbought, "bullish")
        )
        blockers = []
        if rsi_gate:
            op = ">=" if side == "long" else "<="
            blockers.append(f"RSI={last_rsi:.1f}{op}{rsi_threshold:.0f}")
        if not volume_ok:
            blockers.append(f"vol={last_vol:.0f}<=SMA={last_vol_sma:.0f}")
        if not distance_ok:
            blockers.append(f"dist={distance_std:.2f}σ<{self.min_distance_std:.2f}σ")
        if htf_bias == htf_block:
            blockers.append(f"HTF={htf_bias}")
        if not blockers:
            blockers.append("unknown")  # shouldn't happen — every band touch not taken has a reason
        return f"SKIP {side}: " + ", ".join(blockers)
