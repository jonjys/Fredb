import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.stats import compute_stats


@dataclass
class FakeClosed:
    pnl_quote: float
    side: str = "long"


def newest_first(*pnls_oldest_first):
    """Matches StateStore.get_trade_history ordering (newest first)."""
    return [FakeClosed(p) for p in reversed(pnls_oldest_first)]


def test_empty_history_is_all_zeroes_not_a_crash():
    stats = compute_stats([])
    assert stats.total_trades == 0
    assert stats.win_rate_pct == 0.0
    assert stats.profit_factor is None


def test_basic_win_loss_accounting():
    stats = compute_stats(newest_first(10, -5, 20, -5))
    assert stats.total_trades == 4
    assert stats.wins == 2
    assert stats.losses == 2
    assert stats.win_rate_pct == 50.0
    assert stats.net_pnl_quote == 20
    assert stats.gross_profit == 30
    assert stats.gross_loss == 10
    assert stats.profit_factor == 3.0
    assert stats.best_trade_quote == 20
    assert stats.worst_trade_quote == -5


def test_current_streak_counts_forward_from_most_recent():
    # oldest -> newest: win, loss, win, win, win  => currently on 3 wins
    stats = compute_stats(newest_first(5, -2, 3, 4, 6))
    assert stats.current_streak == 3


def test_current_streak_is_negative_while_losing():
    stats = compute_stats(newest_first(5, 5, -1, -2))
    assert stats.current_streak == -2


def test_best_win_streak_is_the_longest_run_ever():
    # oldest -> newest: W W W L W  => best run of 3, current run of 1
    stats = compute_stats(newest_first(1, 2, 3, -1, 4))
    assert stats.best_win_streak == 3
    assert stats.current_streak == 1


def test_profit_factor_undefined_with_no_losses():
    """A flawless record over a handful of trades is not an infinite edge —
    it's an absent denominator, and should read as unknown rather than
    perfect."""
    stats = compute_stats(newest_first(1, 2, 3))
    assert stats.profit_factor is None
    assert stats.win_rate_pct == 100.0


def test_high_win_rate_can_still_be_a_losing_strategy():
    """The exact failure mode win-rate-alone hides: 80% winners, still down
    money overall. Profit factor is what exposes it."""
    stats = compute_stats(newest_first(1, 1, 1, 1, -10))
    assert stats.win_rate_pct == 80.0
    assert stats.net_pnl_quote == -6
    assert stats.profit_factor is not None and stats.profit_factor < 1


def test_per_direction_breakdown():
    trades = [
        FakeClosed(5, "long"), FakeClosed(-2, "long"),
        FakeClosed(7, "short"), FakeClosed(3, "short"),
    ]
    stats = compute_stats(trades)
    assert stats.long_trades == 2
    assert stats.short_trades == 2
    assert stats.long_win_rate_pct == 50.0
    assert stats.short_win_rate_pct == 100.0


def test_averages_are_signed_intuitively():
    stats = compute_stats(newest_first(10, 20, -5, -15))
    assert stats.avg_win_quote == 15.0
    assert stats.avg_loss_quote == -10.0
