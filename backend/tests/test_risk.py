import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings
from app.risk import RiskManager


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
    settings = Settings(**defaults)
    return RiskManager(settings)


def test_size_position_respects_risk_budget():
    risk = make_risk()
    result = risk.size_position(equity=1000, entry_price=100, atr=0.5, atr_pct=0.5)
    assert result is not None
    risk_amount = result.qty * (result.entry_price - result.stop_loss_price)
    assert risk_amount <= 1000 * 0.01 + 1e-6


def test_size_position_capped_by_allocation():
    risk = make_risk(max_concurrent_positions=5, max_risk_per_trade_pct=50)
    result = risk.size_position(equity=1000, entry_price=100, atr=0.1, atr_pct=0.1)
    assert result is not None
    notional = result.qty * result.entry_price
    assert notional <= 1000 / 5 + 1e-6


def test_can_open_new_position_respects_max_concurrent():
    risk = make_risk(max_concurrent_positions=3)
    assert risk.can_open_new_position(2, kill_switch_active=False) is True
    assert risk.can_open_new_position(3, kill_switch_active=False) is False


def test_kill_switch_blocks_new_positions():
    risk = make_risk()
    assert risk.can_open_new_position(0, kill_switch_active=True) is False


def test_daily_drawdown_triggers_kill_switch():
    risk = make_risk(max_daily_loss_pct=5.0)
    assert risk.check_daily_drawdown(equity=940, daily_start_equity=1000) is not None
    assert risk.check_daily_drawdown(equity=960, daily_start_equity=1000) is None


def test_take_profit_should_exceed_round_trip_costs():
    risk = make_risk(take_profit_pct=0.6, taker_fee_pct=0.1, slippage_buffer_pct=0.05)
    assert risk.is_take_profit_worth_it() is True
    risk_bad = make_risk(take_profit_pct=0.1, taker_fee_pct=0.1, slippage_buffer_pct=0.05)
    assert risk_bad.is_take_profit_worth_it() is False
