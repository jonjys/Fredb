"""Short-side correctness.

Every one of these is a sign-convention check. A flipped sign here doesn't
crash anything — it silently reports losses as profits, puts the stop-loss
on the side of the market that can never be reached, or trails a stop the
wrong way. That makes these the highest-value tests in the suite.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings
from app.futures_bot import _directional_pnl
from app.risk import RiskManager
from app.strategy import ScalpingStrategy


def make_risk(**overrides) -> RiskManager:
    defaults = dict(
        max_risk_per_trade_pct=1.0,
        max_concurrent_positions=3,
        take_profit_pct=0.6,
        trailing_stop_pct=0.3,
        stop_loss_pct=0.4,
        atr_multiplier=1.5,
        max_daily_loss_pct=5.0,
        taker_fee_pct=0.1,
        slippage_buffer_pct=0.05,
    )
    defaults.update(overrides)
    return RiskManager(Settings(**defaults))


def make_df(closes):
    closes = np.array(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "timestamp": np.arange(n) * 60_000,
            "open": closes,
            "high": closes * 1.001,
            "low": closes * 0.999,
            "close": closes,
            "volume": np.full(n, 100.0),
        }
    )


# A trend that actually looks like a market: net upward drift, but with real
# pullbacks. A straight line has no losing candles at all, which pins RSI at
# its extreme and is correctly *refused* by the strategy — see
# test_vertical_move_is_refused_not_chased.
TREND_PATTERN = [0.30, -0.25, 0.30, -0.20]


def trending_closes(pattern, n=60, start=100.0):
    closes = [start]
    for i in range(n - 1):
        closes.append(closes[-1] + pattern[i % len(pattern)])
    return closes


def mirrored(pattern):
    return [-d for d in pattern]


# ---- Directional PnL -------------------------------------------------------


def test_short_profits_when_price_falls():
    assert _directional_pnl("short", entry_price=100, current_price=90, qty=2) == 20


def test_short_loses_when_price_rises():
    assert _directional_pnl("short", entry_price=100, current_price=110, qty=2) == -20


def test_long_profits_when_price_rises():
    assert _directional_pnl("long", entry_price=100, current_price=110, qty=2) == 20


def test_long_and_short_are_exact_mirrors():
    long_pnl = _directional_pnl("long", 100, 107, 3)
    short_pnl = _directional_pnl("short", 100, 107, 3)
    assert long_pnl == -short_pnl


# ---- Short sizing / stop placement -----------------------------------------


def test_short_stop_is_above_entry_and_tp_below():
    risk = make_risk()
    result = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=0.5, atr_pct=0.5,
        requested_leverage=5, max_leverage_cap=50, side="short",
    )
    assert result is not None
    assert result.stop_loss_price > result.entry_price, "short stop must sit above entry"
    assert result.take_profit_price < result.entry_price, "short TP must sit below entry"


def test_short_liquidation_is_above_entry_and_beyond_the_stop():
    """A short is liquidated when price rises far enough. The stop must be
    reached first, otherwise the exchange closes the position before our
    risk management ever gets a say."""
    risk = make_risk()
    result = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=0.5, atr_pct=0.5,
        requested_leverage=10, max_leverage_cap=50, side="short",
    )
    assert result is not None
    assert result.liquidation_price > result.entry_price
    assert result.stop_loss_price < result.liquidation_price


def test_long_liquidation_is_below_entry_and_beyond_the_stop():
    risk = make_risk()
    result = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=0.5, atr_pct=0.5,
        requested_leverage=10, max_leverage_cap=50, side="long",
    )
    assert result is not None
    assert result.liquidation_price < result.entry_price
    assert result.stop_loss_price > result.liquidation_price


def test_short_and_long_risk_identical_distance_and_size():
    """Direction must not change how much is risked — only which way the
    levels point."""
    risk = make_risk()
    kwargs = dict(
        equity=1000, entry_price=100, atr=0.5, atr_pct=0.5,
        requested_leverage=5, max_leverage_cap=50,
    )
    long_r = risk.size_position_leveraged(**kwargs, side="long")
    short_r = risk.size_position_leveraged(**kwargs, side="short")
    assert long_r is not None and short_r is not None
    assert long_r.qty == short_r.qty
    assert long_r.leverage == short_r.leverage
    assert long_r.margin_required_quote == short_r.margin_required_quote
    long_stop_distance = long_r.entry_price - long_r.stop_loss_price
    short_stop_distance = short_r.stop_loss_price - short_r.entry_price
    assert abs(long_stop_distance - short_stop_distance) < 1e-9


# ---- Bidirectional signal generation ---------------------------------------


def test_downtrend_produces_a_short_signal():
    strategy = ScalpingStrategy()
    closes = trending_closes(mirrored(TREND_PATTERN))
    signal = strategy.generate_signal(make_df(closes))
    assert signal.action == "short"


def test_uptrend_still_produces_a_long_signal():
    strategy = ScalpingStrategy()
    signal = strategy.generate_signal(make_df(trending_closes(TREND_PATTERN)))
    assert signal.action == "long"


def test_flat_market_produces_no_signal_in_either_direction():
    strategy = ScalpingStrategy()
    signal = strategy.generate_signal(make_df([100.0] * 60))
    assert signal.action == "hold"


def test_long_and_short_signals_are_symmetric():
    """The same market shape, mirrored, must produce the mirrored decision
    with a mirrored RSI. If this drifts, the bot has a directional bias it
    was never meant to have."""
    strategy = ScalpingStrategy()
    up = strategy.generate_signal(make_df(trending_closes(TREND_PATTERN)))
    down = strategy.generate_signal(make_df(trending_closes(mirrored(TREND_PATTERN))))
    assert (up.action, down.action) == ("long", "short")

    up_rsi = float(up.reason.split("RSI=")[1])
    down_rsi = float(down.reason.split("RSI=")[1])
    assert abs((100 - up_rsi) - down_rsi) < 0.5


def test_vertical_move_is_refused_not_chased():
    """A move with zero pullbacks pins RSI at its extreme (100 up / 0 down),
    which is exactly the blow-off condition the overbought/oversold guard
    exists to stay out of.

    Regression guard: RSI previously returned a neutral 50 for the
    no-pullback case because the zero-division fill collapsed "all gains"
    and "no movement" into the same value, so this guard silently passed
    during the most extended moves and the bot bought the top.
    """
    strategy = ScalpingStrategy()
    straight_up = strategy.generate_signal(make_df([100 + i * 0.15 for i in range(60)]))
    straight_down = strategy.generate_signal(make_df([100 - i * 0.15 for i in range(60)]))
    assert straight_up.action == "hold"
    assert straight_down.action == "hold"
