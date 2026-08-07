"""Exit reasons must distinguish a stop-out from a locked-in trailing exit.

The futures trailing stop rewrites stop_loss_price to the trailing level,
because that is where the exchange-native stop order has to sit. That makes
one field serve two outcomes, and labelling both "stop_loss" silently
reported every trailing win as a loss in the trade history — which is
exactly the data you'd use to judge whether the exit rules work.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings
from app.futures_bot import FuturesTradingBot


class _FakeBroker:
    def __init__(self, price):
        self.price = price

    async def get_price(self, symbol):
        return self.price

    async def close(self):
        pass


class _FakeStore:
    def __init__(self):
        self.closed_with = None

    async def update_position(self, *a, **k):
        return None


class _Position:
    def __init__(self, side, stop_loss_price, trailing_active):
        self.id = 1
        self.symbol = "BTC/USDT:USDT"
        self.side = side
        self.qty = 1.0
        self.entry_price = 100.0
        self.stop_loss_price = stop_loss_price
        self.take_profit_price = 106.0 if side == "long" else 94.0
        self.trailing_active = trailing_active
        self.trailing_high = 100.0
        self.stop_order_id = ""
        self.take_profit_order_id = ""
        self.margin_used = 10.0
        self.leverage = 5.0


def _reason_for(side, price, stop_loss_price, trailing_active):
    """Run _manage_position with the close path stubbed, and report the label."""
    bot = FuturesTradingBot.__new__(FuturesTradingBot)
    bot.settings = Settings(trailing_stop_pct=0.3)
    bot.broker = _FakeBroker(price)
    bot.store = _FakeStore()
    bot._last_prices = {}

    captured = {}

    async def fake_close(position, reason):
        captured["reason"] = reason

    bot._close_position = fake_close
    position = _Position(side, stop_loss_price, trailing_active)
    asyncio.run(bot._manage_position(position))
    return captured.get("reason")


def test_long_hard_stop_is_labelled_stop_loss():
    # Not trailing yet, price falls through the protective stop.
    assert _reason_for("long", price=98.0, stop_loss_price=99.0, trailing_active=False) == "stop_loss"


def test_long_trailing_exit_is_labelled_trailing_stop():
    # Trailing active: stop_loss_price now holds the trailing level, and
    # crossing it is a locked-in exit, not a stop-out.
    assert (
        _reason_for("long", price=104.0, stop_loss_price=105.0, trailing_active=True)
        == "trailing_stop"
    )


def test_short_hard_stop_is_labelled_stop_loss():
    # A short is stopped out when price rises through the stop above entry.
    assert _reason_for("short", price=102.0, stop_loss_price=101.0, trailing_active=False) == "stop_loss"


def test_short_trailing_exit_is_labelled_trailing_stop():
    assert (
        _reason_for("short", price=96.0, stop_loss_price=95.0, trailing_active=True)
        == "trailing_stop"
    )
