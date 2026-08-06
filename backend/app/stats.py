"""Trading performance statistics computed from closed positions.

These are the numbers that tell you whether the bot actually has an edge,
as opposed to whether it happens to be up right now. Win rate alone is
famously misleading — a strategy can win 90% of trades and still bleed
money if the 10% of losses are large — which is why profit factor and the
average win/loss sizes are reported alongside it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence


@dataclass
class PerformanceStats:
    total_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    net_pnl_quote: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    avg_win_quote: float
    avg_loss_quote: float
    best_trade_quote: float
    worst_trade_quote: float
    current_streak: int  # positive = consecutive wins, negative = consecutive losses
    best_win_streak: int
    long_trades: int
    short_trades: int
    long_win_rate_pct: float | None
    short_win_rate_pct: float | None


def _win_rate(trades: Sequence) -> float | None:
    if not trades:
        return None
    wins = sum(1 for t in trades if t.pnl_quote > 0)
    return wins / len(trades) * 100


def compute_stats(closed_positions: List) -> PerformanceStats:
    """closed_positions: newest-first (as returned by StateStore.get_trade_history)."""
    if not closed_positions:
        return PerformanceStats(
            total_trades=0, wins=0, losses=0, win_rate_pct=0.0, net_pnl_quote=0.0,
            gross_profit=0.0, gross_loss=0.0, profit_factor=None, avg_win_quote=0.0,
            avg_loss_quote=0.0, best_trade_quote=0.0, worst_trade_quote=0.0,
            current_streak=0, best_win_streak=0, long_trades=0, short_trades=0,
            long_win_rate_pct=None, short_win_rate_pct=None,
        )

    pnls = [p.pnl_quote for p in closed_positions]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    # Profit factor is gross profit / gross loss. Undefined (rather than
    # infinite) with no losses yet — a "perfect" record over three trades
    # says nothing, and reporting it as infinity invites exactly the wrong
    # conclusion.
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    # closed_positions is newest-first, so the current streak runs forward
    # from index 0.
    current_streak = 0
    for pnl in pnls:
        is_win = pnl > 0
        if current_streak == 0:
            current_streak = 1 if is_win else -1
        elif is_win and current_streak > 0:
            current_streak += 1
        elif not is_win and current_streak < 0:
            current_streak -= 1
        else:
            break

    best_win_streak = 0
    run = 0
    for pnl in reversed(pnls):  # oldest-first for a chronological scan
        if pnl > 0:
            run += 1
            best_win_streak = max(best_win_streak, run)
        else:
            run = 0

    longs = [p for p in closed_positions if p.side == "long"]
    shorts = [p for p in closed_positions if p.side == "short"]

    return PerformanceStats(
        total_trades=len(pnls),
        wins=len(wins),
        losses=len(losses),
        win_rate_pct=len(wins) / len(pnls) * 100,
        net_pnl_quote=sum(pnls),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        avg_win_quote=(gross_profit / len(wins)) if wins else 0.0,
        avg_loss_quote=(-gross_loss / len(losses)) if losses else 0.0,
        best_trade_quote=max(pnls),
        worst_trade_quote=min(pnls),
        current_streak=current_streak,
        best_win_streak=best_win_streak,
        long_trades=len(longs),
        short_trades=len(shorts),
        long_win_rate_pct=_win_rate(longs),
        short_win_rate_pct=_win_rate(shorts),
    )
