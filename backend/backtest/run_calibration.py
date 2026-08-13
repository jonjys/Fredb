# backtest/run_calibration.py
"""Phase 1 gate: does the harness reproduce the live bot's own economics?

Runs the backtest with today's actual live default settings (app.config's
Settings() defaults — see backend/app/config.py) over real historical
futures data, using the strategy that is actually deployed
(MeanReversionStrategy, not the legacy ScalpingStrategy this script used
to default to), then runs the same period again with fees and slippage
zeroed out. If the harness is honest, that second run isolates the
signal's own (pre-cost) edge from the cost drag.

Previously this hardcoded a LIVE_SETTINGS snapshot from an August 2026
quant review and defaulted BacktestEngine to ScalpingStrategy — both had
drifted from what's actually live (mean-reversion strategy, corrected
risk/TP settings) and were silently producing numbers for a bot that no
longer exists. Reading straight from Settings() means this can't go
stale the same way again — it always reflects app/config.py's current
defaults, which the live bots also load from unless a Railway env var
overrides them (this script has no way to see those overrides).

Usage: python -m backtest.run_calibration [--days N] [--symbols BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT]
"""
from __future__ import annotations

import argparse
import datetime as dt
import time

from app.config import Settings
from app.mean_reversion import MeanReversionStrategy, attach_htf_bias
from backtest.data import load_klines
from backtest.engine import BacktestEngine
from backtest.report import build_report, print_report


def _load_symbol_with_htf(symbol: str, start: dt.date, end: dt.date, htf_timeframe: str, ema_period: int):
    df_1m = load_klines(symbol, start, end, timeframe="1m")
    df_htf = load_klines(symbol, start, end, timeframe=htf_timeframe)
    return attach_htf_bias(df_1m, df_htf, ema_period=ema_period)


def _make_strategy(settings: Settings) -> MeanReversionStrategy:
    return MeanReversionStrategy(
        bb_period=settings.mr_bb_period,
        bb_std=settings.mr_bb_std,
        rsi_period=settings.mr_rsi_period,
        rsi_oversold=settings.mr_rsi_oversold,
        rsi_overbought=settings.mr_rsi_overbought,
        volume_sma_period=settings.mr_volume_sma_period,
        min_distance_std=settings.mr_min_distance_std,
    )


def run(days: int, symbols: list) -> None:
    end = dt.date.today() - dt.timedelta(days=2)  # daily archives lag by ~1-2 days
    start = end - dt.timedelta(days=days)
    print(f"Loading {', '.join(symbols)} 1m+15m futures data: {start} -> {end} ({days} days)")

    settings = Settings()  # today's actual live defaults, see app/config.py

    t0 = time.time()
    data = {
        sym: _load_symbol_with_htf(sym, start, end, settings.htf_timeframe, settings.htf_ema_period)
        for sym in symbols
    }
    for sym, df in data.items():
        print(f"  {sym}: {len(df)} bars")
    print(f"Loaded in {time.time() - t0:.1f}s")

    print("\n--- Run 1: live settings (fees + slippage on) ---")
    t0 = time.time()
    result = BacktestEngine(settings, data, leverage_mode="auto", strategy=_make_strategy(settings)).run()
    print(f"({time.time() - t0:.1f}s)")
    report = build_report(result)
    print_report(report)

    print("\n--- Run 2: same period, zero fees/slippage (isolates signal edge) ---")
    settings_zc = settings.model_copy(update={"taker_fee_pct": 0.0, "slippage_buffer_pct": 0.0})
    result_zc = BacktestEngine(settings_zc, data, leverage_mode="auto", strategy=_make_strategy(settings_zc)).run()
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
        print(f"Cost share of loss:    {report.cost_share_of_gross_loss_pct:.1f}%")
    print(
        "PASS: costs dominate the loss."
        if net < 0 and report.cost_share_of_gross_loss_pct and report.cost_share_of_gross_loss_pct > 50
        else "Costs are not the dominant factor here — see the signal's own zero-cost result above."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument(
        "--symbols", type=str, default="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT",
        help="comma-separated ccxt futures symbols",
    )
    args = parser.parse_args()
    run(args.days, [s.strip() for s in args.symbols.split(",") if s.strip()])
