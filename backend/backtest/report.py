"""Turns a BacktestResult into the numbers that decide whether a strategy
is worth trading: not just win rate, but how much of the P&L is costs,
what the risk-adjusted return looks like, and how deep the drawdowns get.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from app.stats import PerformanceStats, compute_stats
from backtest.engine import BacktestResult


@dataclass
class BacktestReport:
    stats: PerformanceStats
    gross_pnl: float
    total_fees: float
    total_funding: float
    cost_share_of_gross_loss_pct: Optional[float]
    avg_cost_pct_of_notional: float
    sharpe: Optional[float]
    max_drawdown_pct: float
    max_drawdown_quote: float
    turnover_trades_per_day: float
    ending_balance: float
    kill_switch_count: int


def _sharpe(equity_curve: List[tuple]) -> Optional[float]:
    """Annualized Sharpe from the equity curve's per-bar returns (1m bars).

    Backtest bars are minutes; there are 525,600 of them in a year, so the
    annualization factor is sqrt(525600), not the usual sqrt(252) daily
    figure. A scalping strategy has almost all bars flat (no position
    change), which drags this toward zero — that's a real property of the
    strategy's low time-in-market, not a bug in the calculation.
    """
    if len(equity_curve) < 3:
        return None
    values = [e for _, e in equity_curve]
    returns = [(values[i] - values[i - 1]) / values[i - 1] for i in range(1, len(values)) if values[i - 1] > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    bars_per_year = 365 * 24 * 60
    return (mean / std) * math.sqrt(bars_per_year)


def _max_drawdown(equity_curve: List[tuple]) -> tuple:
    if not equity_curve:
        return 0.0, 0.0
    peak = equity_curve[0][1]
    max_dd_pct = 0.0
    max_dd_quote = 0.0
    for _, equity in equity_curve:
        peak = max(peak, equity)
        dd_quote = peak - equity
        dd_pct = (dd_quote / peak * 100) if peak > 0 else 0.0
        max_dd_pct = max(max_dd_pct, dd_pct)
        max_dd_quote = max(max_dd_quote, dd_quote)
    return max_dd_pct, max_dd_quote


def build_report(result: BacktestResult) -> BacktestReport:
    stats = compute_stats(list(reversed(result.trades)))  # compute_stats expects newest-first

    total_fees = sum(t.fee_paid for t in result.trades)
    total_funding = sum(t.funding_paid for t in result.trades)
    gross_pnl = stats.net_pnl_quote + total_fees + total_funding

    # Defined against the net loss (fees already embedded in it), matching
    # how the live-account review computed it: fees / |net P&L|, not
    # against gross_loss (which only sums losing trades and would double
    # count the fee drag already baked into each of their pnl_quote values).
    cost_share = None
    if stats.net_pnl_quote < 0:
        cost_share = (total_fees + abs(total_funding)) / abs(stats.net_pnl_quote) * 100

    total_notional = sum(t.entry_price * t.qty for t in result.trades)
    avg_cost_pct = (
        (total_fees + abs(total_funding)) / total_notional * 100 if total_notional > 0 else 0.0
    )

    max_dd_pct, max_dd_quote = _max_drawdown(result.equity_curve)

    span_days = 1.0
    if len(result.equity_curve) >= 2:
        span_seconds = (result.equity_curve[-1][0] - result.equity_curve[0][0]).total_seconds()
        span_days = max(span_seconds / 86400, 1.0)
    turnover = stats.total_trades / span_days

    return BacktestReport(
        stats=stats,
        gross_pnl=gross_pnl,
        total_fees=total_fees,
        total_funding=total_funding,
        cost_share_of_gross_loss_pct=cost_share,
        avg_cost_pct_of_notional=avg_cost_pct,
        sharpe=_sharpe(result.equity_curve),
        max_drawdown_pct=max_dd_pct,
        max_drawdown_quote=max_dd_quote,
        turnover_trades_per_day=turnover,
        ending_balance=result.ending_balance,
        kill_switch_count=len(result.kill_switch_events),
    )


def print_report(report: BacktestReport) -> None:
    s = report.stats
    print("=" * 60)
    print(f"Trades:            {s.total_trades}  (long {s.long_trades} / short {s.short_trades})")
    print(f"Win rate:          {s.win_rate_pct:.1f}%")
    print(f"Profit factor:     {s.profit_factor if s.profit_factor is not None else 'n/a (no losses)'}")
    print(f"Gross P&L:         {report.gross_pnl:+.2f}")
    print(f"Fees paid:         -{report.total_fees:.2f}")
    print(f"Funding paid:      {-report.total_funding:+.2f}")
    print(f"Net P&L:           {s.net_pnl_quote:+.2f}")
    print(f"Net P&L / trade:   {(s.net_pnl_quote / s.total_trades) if s.total_trades else 0:+.4f}")
    if report.cost_share_of_gross_loss_pct is not None:
        print(f"Cost share of loss:{report.cost_share_of_gross_loss_pct:.1f}%")
    print(f"Avg cost % of notional (round trip): {report.avg_cost_pct_of_notional:.3f}%")
    print(f"Sharpe (annualized):{report.sharpe if report.sharpe is not None else 'n/a':}")
    print(f"Max drawdown:      {report.max_drawdown_pct:.1f}%  (-{report.max_drawdown_quote:.2f})")
    print(f"Turnover:          {report.turnover_trades_per_day:.2f} trades/day")
    print(f"Kill switch fires: {report.kill_switch_count}")
    print(f"Ending balance:    {report.ending_balance:.2f}")
    print("=" * 60)
