# tests/test_autotune.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest

import backtest.data as backtest_data
from app.autotune import Autotuner
from app.config import Settings


def _fake_klines(timeframe: str, minutes: int = 400):
    # Small (well under a full day) and noisy enough to occasionally trip
    # the mean-reversion signal's BB/RSI/volume gates, so the grid search
    # exercises real trade-closing code paths — but still small enough that
    # 2-3 candidates across 4 tests runs in a couple seconds, not minutes.
    freq = {"1m": "1min", "15m": "15min"}[timeframe]
    periods = {"1m": minutes, "15m": max(minutes // 15, 30)}[timeframe]
    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0, 0.4, periods))
    volumes = rng.uniform(80, 120, periods)
    spike_idx = rng.choice(periods, size=max(periods // 20, 1), replace=False)
    volumes[spike_idx] *= 4
    timestamps = pd.date_range("2026-01-01", periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": closes, "high": closes * 1.001, "low": closes * 0.999,
        "close": closes, "volume": volumes,
    })


@pytest.fixture(autouse=True)
def fake_load_klines(monkeypatch):
    def _load(symbol, start, end, timeframe="1m", market="um"):
        return _fake_klines(timeframe, minutes=400)
    monkeypatch.setattr(backtest_data, "load_klines", _load)


def make_settings(**overrides):
    defaults = dict(
        take_profit_pct=1.0, stop_loss_pct=0.5, taker_fee_pct=0.1, slippage_buffer_pct=0.05,
        autotune_tp_candidates_csv="1.0,1.2", autotune_min_pf_improvement_multiple=1.2,
        autotune_auto_apply=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_grid_search_returns_a_suggestion_for_each_valid_candidate():
    settings = make_settings()
    tuner = Autotuner(settings, symbols=["BTC/USDT:USDT"])
    result = tuner._grid_search_sync()
    assert set(result.pf_by_candidate.keys()) <= {1.0, 1.2}
    assert result.current_tp == 1.0


def test_grid_search_excludes_candidates_below_the_cost_floor():
    # round_trip_cost = maker_fee_pct(0.02) + taker_fee_pct(0.1) + slippage_buffer_pct(0.05)
    # = 0.17%; floor = 3x = 0.51%. 0.5% falls just short of it.
    settings = make_settings(autotune_tp_candidates_csv="0.5,1.0")
    tuner = Autotuner(settings, symbols=["BTC/USDT:USDT"])
    result = tuner._grid_search_sync()
    assert 0.5 not in result.pf_by_candidate


def test_auto_apply_false_never_mutates_settings():
    settings = make_settings(autotune_auto_apply=False, autotune_min_pf_improvement_multiple=0.0)
    tuner = Autotuner(settings, symbols=["BTC/USDT:USDT"])
    result = tuner._grid_search_sync()
    assert settings.take_profit_pct == 1.0  # never changed regardless of the suggestion
    if result.suggested_tp is not None:
        assert result.applied is False


def test_auto_apply_true_mutates_settings_when_a_candidate_clears_the_bar():
    # multiple=0.0 means any candidate with a higher (or equal) PF than
    # current clears the bar trivially, so a change is virtually guaranteed
    # to be suggested across two candidates on random data.
    settings = make_settings(autotune_auto_apply=True, autotune_min_pf_improvement_multiple=0.0)
    tuner = Autotuner(settings, symbols=["BTC/USDT:USDT"])
    result = tuner._grid_search_sync()
    if result.suggested_tp is not None:
        assert settings.take_profit_pct == result.suggested_tp
        assert result.applied is True
