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


def test_max_safe_leverage_decreases_as_stop_widens():
    risk = make_risk()
    tight_stop_leverage = risk.max_safe_leverage(stop_distance_pct=0.2)
    wide_stop_leverage = risk.max_safe_leverage(stop_distance_pct=2.0)
    assert tight_stop_leverage > wide_stop_leverage
    assert wide_stop_leverage >= 1.0


def test_max_safe_leverage_stays_low_for_very_wide_stops():
    risk = make_risk()
    leverage = risk.max_safe_leverage(stop_distance_pct=50.0)
    assert 1.0 <= leverage < 2.0


def test_size_position_leveraged_clamps_high_requested_leverage():
    """A wide (2%) stop should not survive anywhere near 50x — the safety
    clamp must cap it far below whatever was requested."""
    risk = make_risk(stop_loss_pct=2.0, atr_multiplier=1.5)
    result = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=2.0, atr_pct=2.0, requested_leverage=50, max_leverage_cap=50
    )
    assert result is not None
    assert result.leverage < 50
    assert result.leverage >= 1.0


def test_size_position_leveraged_respects_hard_cap():
    """Even when the liquidation-safety math would allow more, the
    configured hard cap must win."""
    risk = make_risk(stop_loss_pct=0.05, atr_multiplier=0.1)
    result = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=0.01, atr_pct=0.01, requested_leverage=100, max_leverage_cap=10
    )
    assert result is not None
    assert result.leverage <= 10


def test_size_position_leveraged_qty_matches_spot_risk_formula():
    """Leverage must not change how much is risked per trade — only margin
    efficiency. qty/stop/TP should be identical to the unleveraged sizing."""
    risk = make_risk()
    spot = risk.size_position(equity=1000, entry_price=100, atr=0.5, atr_pct=0.5)
    leveraged = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=0.5, atr_pct=0.5, requested_leverage=5, max_leverage_cap=50
    )
    assert spot is not None and leveraged is not None
    assert leveraged.qty == spot.qty
    assert leveraged.stop_loss_price == spot.stop_loss_price
    assert leveraged.take_profit_price == spot.take_profit_price


def test_margin_required_shrinks_with_leverage():
    risk = make_risk()
    low_lev = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=0.5, atr_pct=0.5, requested_leverage=2, max_leverage_cap=50
    )
    high_lev = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=0.5, atr_pct=0.5, requested_leverage=5, max_leverage_cap=50
    )
    assert low_lev is not None and high_lev is not None
    assert high_lev.margin_required_quote < low_lev.margin_required_quote


def test_liquidation_price_below_entry_for_long():
    risk = make_risk()
    result = risk.size_position_leveraged(
        equity=1000, entry_price=100, atr=0.5, atr_pct=0.5, requested_leverage=5, max_leverage_cap=50
    )
    assert result is not None
    assert result.liquidation_price < result.entry_price
    # Stop-loss must trigger before liquidation, not after.
    assert result.stop_loss_price > result.liquidation_price
