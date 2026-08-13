# tests/test_regime.py
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import app.regime as regime_module
from app.config import Settings
from app.regime import BtcDominanceTracker, orderbook_imbalance, regime_block_reason


class FakeBroker:
    def __init__(self, book):
        self.book = book

    async def get_order_book(self, symbol, limit):
        return self.book


def test_orderbook_imbalance_balanced_book_is_one():
    book = {"bids": [[100.0, 10.0], [99.0, 10.0]], "asks": [[101.0, 10.0], [102.0, 10.0]]}
    assert orderbook_imbalance(book, depth_levels=5) == pytest.approx(1.0)


def test_orderbook_imbalance_ask_heavy_book_below_one():
    book = {"bids": [[100.0, 5.0]], "asks": [[101.0, 20.0]]}
    assert orderbook_imbalance(book, depth_levels=5) == pytest.approx(0.25)


def test_orderbook_imbalance_none_for_empty_book():
    assert orderbook_imbalance({"bids": [], "asks": []}, depth_levels=5) is None
    assert orderbook_imbalance({"bids": [[100.0, 1.0]], "asks": []}, depth_levels=5) is None


def test_orderbook_imbalance_respects_depth_levels():
    # Only the top 1 level should count on each side.
    book = {"bids": [[100.0, 10.0], [99.0, 1000.0]], "asks": [[101.0, 10.0], [102.0, 1000.0]]}
    assert orderbook_imbalance(book, depth_levels=1) == pytest.approx(1.0)


def test_btc_dominance_change_none_without_enough_history():
    tracker = BtcDominanceTracker()
    orig = regime_module._fetch_btc_dominance_sync
    regime_module._fetch_btc_dominance_sync = lambda: 55.0
    try:
        result = asyncio.run(tracker.get_change_1h_pct(refresh_seconds=0.01))
        assert result is None  # only one sample so far
    finally:
        regime_module._fetch_btc_dominance_sync = orig


def test_btc_dominance_change_computed_once_an_hour_of_history_exists():
    tracker = BtcDominanceTracker()
    tracker._history = [(time.time() - 3700, 50.0), (time.time(), 51.5)]
    # No refresh needed — history already covers >1h and is fresh enough.
    result = asyncio.run(tracker.get_change_1h_pct(refresh_seconds=1_000_000))
    assert result == pytest.approx(1.5)


def test_btc_dominance_fails_open_on_fetch_error():
    tracker = BtcDominanceTracker()
    orig = regime_module._fetch_btc_dominance_sync

    def boom():
        raise RuntimeError("network down")

    regime_module._fetch_btc_dominance_sync = boom
    try:
        result = asyncio.run(tracker.get_change_1h_pct(refresh_seconds=0.01))
        assert result is None
    finally:
        regime_module._fetch_btc_dominance_sync = orig


def _settings(**overrides):
    defaults = dict(regime_btc_dominance_enabled=False, regime_orderbook_imbalance_min=0.7)
    defaults.update(overrides)
    return Settings(**defaults)


def test_regime_blocks_long_on_ask_heavy_book():
    broker = FakeBroker({"bids": [[100.0, 5.0]], "asks": [[101.0, 20.0]]})  # imbalance 0.25
    reason = asyncio.run(regime_block_reason(broker, "BTC/USDT", "long", _settings()))
    assert reason is not None and "ask-heavy" in reason


def test_regime_blocks_short_on_bid_heavy_book():
    broker = FakeBroker({"bids": [[100.0, 20.0]], "asks": [[101.0, 5.0]]})  # imbalance 4.0
    reason = asyncio.run(regime_block_reason(broker, "BTC/USDT", "short", _settings()))
    assert reason is not None and "bid-heavy" in reason


def test_regime_passes_balanced_book():
    broker = FakeBroker({"bids": [[100.0, 10.0]], "asks": [[101.0, 10.0]]})
    assert asyncio.run(regime_block_reason(broker, "BTC/USDT", "long", _settings())) is None
    assert asyncio.run(regime_block_reason(broker, "BTC/USDT", "short", _settings())) is None


def test_regime_fails_open_when_orderbook_fetch_raises():
    class BrokenBroker:
        async def get_order_book(self, symbol, limit):
            raise RuntimeError("exchange down")

    reason = asyncio.run(regime_block_reason(BrokenBroker(), "BTC/USDT", "long", _settings()))
    assert reason is None
