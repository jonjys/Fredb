"""Backtest engine mechanics: entries reuse RiskManager's own sizing math,
intrabar stop/TP/trailing simulation matches futures_bot's live semantics
(same exit-reason distinction test_exit_labelling.py guards on the live
side), and the daily kill switch actually blocks new entries.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings
from app.risk import RiskManager
from backtest.engine import BacktestEngine, BacktestPosition, _simulate_fee_and_slippage

SYMBOL = "BTC/USDT:USDT"


def make_settings(**overrides):
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
        futures_paper_starting_balance=1000.0,
        futures_max_leverage=50.0,
        futures_leverage_default=8.0,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def make_df(closes, start="2026-01-01"):
    n = len(closes)
    closes = np.array(closes, dtype=float)
    highs = closes * 1.001
    lows = closes * 0.999
    volumes = np.full(n, 100.0)
    timestamps = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"timestamp": timestamps, "open": closes, "high": highs, "low": lows, "close": closes, "volume": volumes}
    )


def uptrend_closes(flat_bars=40, trend_bars=60):
    """Same oscillating-ramp shape as test_strategy.py's long-signal fixture,
    just with a flat lead-in so a 100-bar signal window (matching
    futures_bot's get_ohlcv(limit=100)) is available on the last bar."""
    closes = [100.0] * flat_bars
    for i in range(trend_bars):
        closes.append(closes[-1] + [0.30, -0.25, 0.30, -0.20][i % 4])
    return closes


def make_engine(settings, df, **kwargs):
    return BacktestEngine(settings, {SYMBOL: df}, leverage_mode=kwargs.pop("leverage_mode", "fixed"),
                           fixed_leverage=kwargs.pop("fixed_leverage", 5.0), **kwargs)


# ---- Fee/slippage primitive -------------------------------------------------

def test_simulate_fee_and_slippage_matches_paper_broker_formula():
    settings = make_settings(slippage_buffer_pct=0.05)
    assert _simulate_fee_and_slippage(settings, 100.0, "buy") == 100.0 * 1.0005
    assert _simulate_fee_and_slippage(settings, 100.0, "sell") == 100.0 * 0.9995


# ---- Entries reuse RiskManager exactly --------------------------------------

def test_entry_sizing_matches_risk_manager_directly():
    settings = make_settings()
    df = make_df(uptrend_closes())
    engine = make_engine(settings, df, fixed_leverage=5.0)
    result = engine.run()

    assert len(result.trades) == 1  # only closed via the forced end-of-backtest close
    trade = result.trades[0]
    assert trade.reason == "backtest_end"
    assert trade.side == "long"

    # Recompute what RiskManager would have produced for the same signal
    # inputs and confirm the engine's fill matches it (minus fee/slippage,
    # which the engine applies on top the same way PaperFuturesBroker does).
    risk = RiskManager(settings)
    window = df.iloc[:100]
    from app.strategy import ScalpingStrategy
    signal = ScalpingStrategy().generate_signal(window)
    sizing = risk.size_position_leveraged(
        settings.futures_paper_starting_balance, signal.close, signal.atr, signal.atr_pct,
        5.0, settings.futures_max_leverage, side="long",
    )
    assert sizing is not None
    assert trade.qty == sizing.qty
    assert trade.entry_price == _simulate_fee_and_slippage(settings, signal.close, "buy")


# ---- Intrabar stop / trailing mechanics (position management only) ---------

def _bare_engine(settings=None):
    settings = settings or make_settings()
    df = make_df([100.0] * 5)  # unused for these tests; just needs a valid frame
    return make_engine(settings, df)


def _inject_long(engine, entry=100.0, stop=99.6, tp=100.6):
    engine.positions[SYMBOL] = BacktestPosition(
        symbol=SYMBOL, side="long", qty=1.0, entry_price=entry, leverage=5.0,
        margin_used=20.0, stop_loss_price=stop, take_profit_price=tp,
        trailing_active=False, trailing_high=entry, opened_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )


def _bar(open_, high, low, close):
    return pd.Series({"open": open_, "high": high, "low": low, "close": close})


def test_long_hard_stop_closes_and_labels_stop_loss():
    engine = _bare_engine()
    _inject_long(engine, entry=100.0, stop=99.6, tp=100.6)
    engine._manage_position_bar(SYMBOL, _bar(100.0, 100.1, 99.5, 99.7), pd.Timestamp("2026-01-01T00:01", tz="UTC"))

    assert SYMBOL not in engine.positions
    assert len(engine.trades) == 1
    assert engine.trades[0].reason == "stop_loss"
    assert engine.trades[0].exit_price == _simulate_fee_and_slippage(engine.settings, 99.6, "sell")


def test_long_take_profit_activates_trailing_without_closing():
    engine = _bare_engine()
    _inject_long(engine, entry=100.0, stop=99.6, tp=100.6)
    engine._manage_position_bar(SYMBOL, _bar(100.5, 100.8, 100.4, 100.7), pd.Timestamp("2026-01-01T00:01", tz="UTC"))

    assert SYMBOL in engine.positions
    assert len(engine.trades) == 0
    position = engine.positions[SYMBOL]
    assert position.trailing_active is True
    assert position.trailing_high == 100.8
    expected_stop = 100.8 * (1 - engine.settings.trailing_stop_pct / 100)
    assert position.stop_loss_price == expected_stop


def test_long_trailing_stop_ratchets_up_then_closes_as_trailing_stop():
    engine = _bare_engine()
    _inject_long(engine, entry=100.0, stop=99.6, tp=100.6)
    ts = pd.Timestamp("2026-01-01T00:01", tz="UTC")

    # Bar 1: TP touched, trailing activates at high=100.8.
    engine._manage_position_bar(SYMBOL, _bar(100.5, 100.8, 100.4, 100.7), ts)
    stop_after_activation = engine.positions[SYMBOL].stop_loss_price

    # Bar 2: price extends further (ratchets the trailing stop up).
    engine._manage_position_bar(SYMBOL, _bar(100.7, 101.5, 100.6, 101.0), ts + pd.Timedelta(minutes=1))
    ratcheted_stop = engine.positions[SYMBOL].stop_loss_price
    assert ratcheted_stop > stop_after_activation

    # Bar 3: price reverses through the ratcheted (not the original) stop.
    engine._manage_position_bar(
        SYMBOL, _bar(101.0, 101.1, ratcheted_stop - 0.05, ratcheted_stop - 0.01), ts + pd.Timedelta(minutes=2)
    )
    assert SYMBOL not in engine.positions
    assert engine.trades[-1].reason == "trailing_stop"


def test_short_hard_stop_closes_and_labels_stop_loss():
    engine = _bare_engine()
    engine.positions[SYMBOL] = BacktestPosition(
        symbol=SYMBOL, side="short", qty=1.0, entry_price=100.0, leverage=5.0,
        margin_used=20.0, stop_loss_price=100.4, take_profit_price=99.4,
        trailing_active=False, trailing_high=100.0, opened_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )
    engine._manage_position_bar(SYMBOL, _bar(100.0, 100.5, 99.9, 100.3), pd.Timestamp("2026-01-01T00:01", tz="UTC"))

    assert SYMBOL not in engine.positions
    assert engine.trades[-1].reason == "stop_loss"


# ---- Daily kill switch ------------------------------------------------------

def test_daily_drawdown_kill_switch_force_closes_and_blocks_new_entries():
    # Very tight daily loss cap so a single stopped-out trade trips it.
    settings = make_settings(max_daily_loss_pct=0.5, max_risk_per_trade_pct=5.0)
    df = make_df(uptrend_closes())
    engine = make_engine(settings, df, fixed_leverage=5.0)

    # Manually seed an open position at a large unrealized loss to force
    # the drawdown check without depending on exact strategy timing.
    engine.daily_start_equity = 1000.0
    engine.balance = 1000.0 - 20.0  # position margin already deducted
    engine.positions[SYMBOL] = BacktestPosition(
        symbol=SYMBOL, side="long", qty=1.0, entry_price=100.0, leverage=5.0,
        margin_used=20.0, stop_loss_price=50.0, take_profit_price=200.0,  # far away, won't hard-stop this bar
        trailing_active=False, trailing_high=100.0, opened_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )
    indexed = {SYMBOL: df.set_index("timestamp")}
    ts = df["timestamp"].iloc[0]
    # Force a big unrealized loss via the equity calc by dropping the mark price.
    indexed[SYMBOL].loc[ts, "close"] = 90.0

    engine._on_bar(ts, 0, indexed)

    assert engine.kill_switch is True
    assert len(engine.kill_switch_events) == 1
    assert SYMBOL not in engine.positions
    assert engine.trades[-1].reason == "emergency_kill"

    # Kill switch active: no new entries even with a valid signal window.
    positions_before = len(engine.positions)
    for i in range(1, len(df)):
        ts_i = df["timestamp"].iloc[i]
        if ts_i not in indexed[SYMBOL].index:
            continue
        engine._on_bar(ts_i, i, indexed)
    assert len(engine.positions) == positions_before == 0
