"""Walk-forward split: roll a train/test window across the data instead of
backtesting the whole history in one shot. A single full-period backtest
can't tell you whether a result is a real edge or a lucky sample; rolling
windows at least show whether performance holds up out-of-sample as the
market regime shifts underneath the strategy.

There is no "training" step yet (the strategy has no fitted parameters —
EMA/RSI/ATR periods are fixed), so right now this just reports whether the
*same* fixed-rule strategy holds up test-window over test-window. It
becomes load-bearing once Phase 2 (learned features/thresholds) exists:
fit on the train slice, evaluate only on the test slice.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

from app.config import Settings
from backtest.engine import BacktestEngine
from backtest.report import BacktestReport, build_report


@dataclass
class WalkForwardWindow:
    train_start: dt.date
    train_end: dt.date
    test_start: dt.date
    test_end: dt.date
    report: BacktestReport


def split_windows(
    start: dt.date, end: dt.date, train_days: int = 60, test_days: int = 14
) -> List[tuple]:
    """Non-overlapping (train_start, train_end, test_start, test_end) tuples
    rolled forward by test_days each step. Train windows are informational
    only until there's a fitted step that uses them."""
    windows = []
    cursor = start
    while True:
        train_start = cursor
        train_end = train_start + dt.timedelta(days=train_days)
        test_start = train_end
        test_end = test_start + dt.timedelta(days=test_days)
        if test_end > end:
            break
        windows.append((train_start, train_end, test_start, test_end))
        cursor = cursor + dt.timedelta(days=test_days)
    return windows


def _slice(df: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
    mask = (df["timestamp"].dt.date >= start) & (df["timestamp"].dt.date < end)
    return df.loc[mask].reset_index(drop=True)


def run_walk_forward(
    settings: Settings,
    full_data: Dict[str, pd.DataFrame],
    start: dt.date,
    end: dt.date,
    train_days: int = 60,
    test_days: int = 14,
    leverage_mode: str = "auto",
) -> List[WalkForwardWindow]:
    results = []
    for train_start, train_end, test_start, test_end in split_windows(start, end, train_days, test_days):
        test_data = {sym: _slice(df, test_start, test_end) for sym, df in full_data.items()}
        if any(len(df) < 200 for df in test_data.values()):
            continue  # not enough bars in this slice to mean anything
        engine = BacktestEngine(settings, test_data, leverage_mode=leverage_mode)
        result = engine.run()
        results.append(
            WalkForwardWindow(
                train_start=train_start, train_end=train_end,
                test_start=test_start, test_end=test_end,
                report=build_report(result),
            )
        )
    return results


def print_walk_forward(windows: List[WalkForwardWindow]) -> None:
    print(f"{'test window':<25} {'trades':>7} {'win%':>6} {'PF':>6} {'net':>10} {'maxDD%':>8}")
    for w in windows:
        s = w.report.stats
        pf = f"{s.profit_factor:.2f}" if s.profit_factor is not None else "n/a"
        window_label = f"{w.test_start}..{w.test_end}"
        print(
            f"{window_label:<25} {s.total_trades:>7} {s.win_rate_pct:>5.1f}% {pf:>6} "
            f"{s.net_pnl_quote:>10.2f} {w.report.max_drawdown_pct:>7.1f}%"
        )
