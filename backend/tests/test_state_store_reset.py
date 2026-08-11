"""reset_paper_account must leave the store looking like a fresh install:
no positions, no trades, no equity history, and BotState back to defaults
(including the new circuit-breaker fields) — this is what the dashboard's
"reset to $1000" button calls.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import Position, Trade
from app.state_store import StateStore


def _make_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # StateStore creates it fresh
    store = StateStore(path)
    store.init(1000.0)
    return store


def test_reset_wipes_positions_trades_and_equity():
    store = _make_store()

    async def scenario():
        position = await store.open_position(
            Position(symbol="BTC/USDT", side="long", entry_price=100.0, qty=1.0,
                     stop_loss_price=99.0, take_profit_price=101.0)
        )
        await store.record_trade(
            Trade(position_id=position.id, symbol="BTC/USDT", side="buy",
                  trade_type="entry", price=100.0, qty=1.0)
        )
        await store.close_position(position.id, 105.0, 5.0, 5.0, "take_profit")
        await store.record_equity(1005.0, 5.0)
        await store.update_state(
            running=True, kill_switch=True, kill_switch_reason="test",
            consecutive_losses=3, throttle_paused_until=999999.0, reduced_size_trades_remaining=2,
        )

        await store.reset_paper_account(1000.0)

        open_positions = await store.get_open_positions()
        trade_history = await store.get_trade_history()
        equity_history = await store.get_equity_history()
        state = await store.get_state()
        return open_positions, trade_history, equity_history, state

    open_positions, trade_history, equity_history, state = asyncio.run(scenario())

    assert open_positions == []
    assert trade_history == []
    assert equity_history == []
    assert state.running is False
    assert state.kill_switch is False
    assert state.kill_switch_reason == ""
    assert state.paper_balance == 1000.0
    assert state.daily_start_equity == 1000.0
    assert state.consecutive_losses == 0
    assert state.throttle_paused_until == 0.0
    assert state.reduced_size_trades_remaining == 0


def test_reset_uses_the_given_starting_balance():
    store = _make_store()
    asyncio.run(store.reset_paper_account(2500.0))
    state = asyncio.run(store.get_state())
    assert state.paper_balance == 2500.0
    assert state.daily_start_equity == 2500.0
