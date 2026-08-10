# Backtest harness

Offline backtesting for the futures strategy. Reuses `app.strategy.ScalpingStrategy`
and `app.risk.RiskManager` directly — a backtest run exercises the same
decision code that runs live, not a reimplementation of it.

## Setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-backtest.txt
```

`requirements-backtest.txt` adds `requests` (to fetch historical data) and
`pyarrow` (to cache it as parquet) on top of the normal backend deps. It is
not installed in the production Docker image — the Dockerfile only copies
`app/`.

## Data source

Historical 1-minute OHLCV klines come from
[data.binance.vision](https://data.binance.vision), Binance's public
archive of daily/monthly kline ZIPs. This is a static file archive, not
the trading API — it's reachable even in network environments where
`api.binance.com` is geo-blocked. `backtest/data.py` downloads and caches
files under `backend/data/klines_cache/` (gitignored) as parquet, so
repeat runs don't re-download.

## Calibration (Phase 1 gate)

Before trusting anything downstream (features, ML models), the harness
must reproduce the live bot's own economics:

```bash
python -m backtest.run_calibration --days 60
```

This runs two backtests over the same real BTC/ETH history with the
settings currently live on Railway: one with fees/slippage on, one with
them zeroed out. If the harness is honest, the cost-on run's losses
should be dominated by fees/slippage rather than bad signal direction —
matching what the live trade history review found (91.5% of realized
losses were costs, not direction). A calibration run on 2026-06-09 to
2026-08-08 measured an 89.6% cost share, confirming the harness reproduces
that finding.

## Walk-forward

```python
from backtest.walkforward import run_walk_forward, print_walk_forward
windows = run_walk_forward(settings, data, start, end, train_days=60, test_days=14)
print_walk_forward(windows)
```

Rolls a test window forward across the full range so a result can't be a
single lucky (or unlucky) sample. There's no fitted "train" step yet since
the strategy has no learned parameters — that becomes load-bearing once
Phase 2 features/models exist.

## Layout

- `data.py` — historical kline acquisition + parquet caching
- `engine.py` — event-driven replay: walks bars, calls the real strategy/risk
  code, simulates intrabar stop/TP/trailing fills from OHLC, applies the same
  fee/slippage formulas as `PaperFuturesBroker`
- `report.py` — turns a backtest run into profit factor, Sharpe, max
  drawdown, cost share, turnover (reuses `app.stats.compute_stats`)
- `walkforward.py` — rolling train/test window splitting
- `run_calibration.py` — the Phase 1 gate script described above
