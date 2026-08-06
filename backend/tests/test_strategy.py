import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.strategy import ScalpingStrategy


def make_df(closes):
    n = len(closes)
    closes = np.array(closes, dtype=float)
    highs = closes * 1.001
    lows = closes * 0.999
    opens = closes
    volumes = np.full(n, 100.0)
    timestamps = np.arange(n) * 60_000
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def test_hold_when_not_enough_candles():
    strategy = ScalpingStrategy()
    df = make_df([100, 101, 102])
    signal = strategy.generate_signal(df)
    assert signal.action == "hold"


def test_long_signal_on_uptrend():
    strategy = ScalpingStrategy()
    # Uptrend with realistic pullbacks => EMA9 > EMA21, RSI in the healthy
    # band, no BB overextension. (A pullback-free ramp is deliberately
    # refused instead — see tests/test_short_side.py.)
    closes = [100.0]
    for i in range(59):
        closes.append(closes[-1] + [0.30, -0.25, 0.30, -0.20][i % 4])
    signal = strategy.generate_signal(make_df(closes))
    assert signal.action == "long"


def test_hold_on_flat_market():
    strategy = ScalpingStrategy()
    closes = [100.0] * 60
    df = make_df(closes)
    signal = strategy.generate_signal(df)
    assert signal.action == "hold"
