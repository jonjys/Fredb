"""Phase 1 gate: does the harness reproduce the live bot's own economics?

Runs the backtest with the exact settings currently live on Railway
(max_risk_per_trade_pct=7, atr_multiplier=5, trailing_stop_pct=0.3,
max_daily_loss_pct=50, etc. — see the quant review for how these were
read off the live /api/settings endpoint) over real historical BTC/ETH
futures data, then runs the same period again with fees and slippage
zeroed out. If the harness is honest, that second run should isolate
the signal's own (pre-cost) edge from the cost drag — the same
decomposition the live-trade-history review found: costs are 91.5% of
realized losses, not bad signal direction.

Usage: python -m backtest.run_calibration [--days N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import time

from app.config import Settings
from backtest.data import load_klines
from backtest.engine import BacktestEngine
from backtest.report import build_report, print_report

# Mirrors the live Railway /api/settings values at the time of the quant
# review (2026-08). If the live bot's settings have since changed (e.g.
# Phase 0 recommendations applied), update this to match before trusting
# a calibration run against them.
LIVE_SETTINGS = dict(
    max_risk_per_trade_pct=7.0,
    max_concurrent_positions=1,
    take_profit_pct=0.6,
    trailing_stop_pct=0.3,
    stop_loss_pct=0.4,
    atr_multiplier=5.0,
    max_daily_loss_pct=50.0,
    taker_fee_pct=0.1,
    slippage_buffer_pct=0.05,
    poll_interval_seconds=1.0,
    futures_paper_starting_balance=1000.0,
    futures_max_leverage=50.0,
    futures_leverage_default=8.0,
)


def run(days: int) -> None:
    end = dt.date.today() - dt.timedelta(days=2)  # daily archives lag by ~1-2 days
    start = end - dt.timedelta(days=days)
    print(f"Loading BTC/ETH 1m futures data: {start} -> {end} ({days} days)")

    t0 = time.time()
    btc = load_klines("BTC/USDT:USDT", start, end)
    eth = load_klines("ETH/USDT:USDT", start, end)
    data = {"BTC/USDT:USDT": btc, "ETH/USDT:USDT": eth}
    print(f"Loaded {len(btc)} BTC bars, {len(eth)} ETH bars in {time.time() - t0:.1f}s")

    print("\n--- Run 1: live settings (fees + slippage on) ---")
    settings = Settings(**LIVE_SETTINGS)
    t0 = time.time()
    result = BacktestEngine(settings, data, leverage_mode="auto").run()
    print(f"({time.time() - t0:.1f}s)")
    report = build_report(result)
    print_report(report)

    print("\n--- Run 2: same period, zero fees/slippage (isolates signal edge) ---")
    zero_cost = dict(LIVE_SETTINGS, taker_fee_pct=0.0, slippage_buffer_pct=0.0)
    settings_zc = Settings(**zero_cost)
    result_zc = BacktestEngine(settings_zc, data, leverage_mode="auto").run()
    report_zc = build_report(result_zc)
    print_report(report_zc)

    print("\n--- Calibration verdict ---")
    net = report.stats.net_pnl_quote
    net_zc = report_zc.stats.net_pnl_quote
    cost_drag = net_zc - net
    print(f"Net P&L with costs:    {net:+.2f}")
    print(f"Net P&L zero-cost:     {net_zc:+.2f}")
    print(f"Cost drag:             {cost_drag:+.2f}  ({report.total_fees + report.total_funding:.2f} fees+funding)")
    if report.cost_share_of_gross_loss_pct is not None:
        print(f"Cost share of loss:    {report.cost_share_of_gross_loss_pct:.1f}%  (live measured: 91.5%)")
    print(
        "PASS: costs dominate the loss, matching the live-account finding."
        if net < 0 and report.cost_share_of_gross_loss_pct and report.cost_share_of_gross_loss_pct > 50
        else "REVIEW: cost structure doesn't dominate here — re-check before trusting downstream results."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    run(args.days)
