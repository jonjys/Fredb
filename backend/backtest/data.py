"""Historical kline acquisition from Binance's public data archive.

data.binance.vision hosts daily and monthly ZIPs of raw kline data going
back to 2020 for USDT-M futures. It is a static file archive (not the
trading API), which matters here: api.binance.com is geo-blocked from
this environment, but data.binance.vision is reachable, so it is the only
viable source of real historical bars to backtest against.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger("tradingbot.backtest.data")

BASE_URL = "https://data.binance.vision/data/futures/um"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "klines_cache"

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def _to_archive_symbol(symbol: str) -> str:
    """"BTC/USDT:USDT" (ccxt unified futures symbol) -> "BTCUSDT" (archive naming)."""
    base = symbol.split(":")[0]
    return base.replace("/", "")


def _month_range(start: dt.date, end: dt.date):
    cur = dt.date(start.year, start.month, 1)
    while cur <= end:
        yield cur
        cur = dt.date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)


def _month_end(month_start: dt.date) -> dt.date:
    next_month = dt.date(month_start.year + (month_start.month == 12), month_start.month % 12 + 1, 1)
    return next_month - dt.timedelta(days=1)


def _read_kline_csv(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw))
    # Older archive files have no header row (12 bare columns); newer ones do.
    if df.columns[0] not in ("open_time",):
        df = pd.read_csv(io.BytesIO(raw), names=KLINE_COLUMNS, header=None)
    return df[["open_time", "open", "high", "low", "close", "volume"]]


def _fetch_zip_csv(url: str) -> Optional[pd.DataFrame]:
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        return None
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name)
    return _read_kline_csv(raw)


def _cached_fetch(url: str, cache_path: Path) -> Optional[pd.DataFrame]:
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    df = _fetch_zip_csv(url)
    if df is None:
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path)
    return df


def load_klines(
    symbol: str,
    start: dt.date,
    end: dt.date,
    timeframe: str = "1m",
    market: str = "um",
) -> pd.DataFrame:
    """Return 1m OHLCV bars for `symbol` covering [start, end], deduped and sorted.

    Uses monthly archives for any calendar month fully inside the range
    (cheap: one request per month) and falls back to daily archives for the
    partial months at the edges. Every fetched file is cached to disk as
    parquet so repeat runs (and repeat backtest parameter sweeps) don't
    re-download.
    """
    archive_symbol = _to_archive_symbol(symbol)
    frames = []

    for month_start in _month_range(start, end):
        month_last = _month_end(month_start)
        full_month = month_start >= start and month_last <= end

        if full_month:
            ym = month_start.strftime("%Y-%m")
            url = f"{BASE_URL}/monthly/klines/{archive_symbol}/{timeframe}/{archive_symbol}-{timeframe}-{ym}.zip"
            cache_path = CACHE_DIR / market / archive_symbol / timeframe / f"{ym}.parquet"
            df = _cached_fetch(url, cache_path)
            if df is None:
                logger.warning("No monthly archive for %s %s, falling back to daily", archive_symbol, ym)
                full_month = False
            else:
                frames.append(df)

        if not full_month:
            day = max(month_start, start)
            last_day = min(month_last, end)
            while day <= last_day:
                ds = day.strftime("%Y-%m-%d")
                url = f"{BASE_URL}/daily/klines/{archive_symbol}/{timeframe}/{archive_symbol}-{timeframe}-{ds}.zip"
                cache_path = CACHE_DIR / market / archive_symbol / timeframe / f"daily-{ds}.parquet"
                df = _cached_fetch(url, cache_path)
                if df is not None:
                    frames.append(df)
                else:
                    logger.warning("No daily archive for %s %s", archive_symbol, ds)
                day += dt.timedelta(days=1)

    if not frames:
        raise ValueError(f"No kline data found for {symbol} between {start} and {end}")

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset="open_time").sort_values("open_time").reset_index(drop=True)
    out["timestamp"] = pd.to_datetime(out["open_time"], unit="ms", utc=True)
    return out[["timestamp", "open", "high", "low", "close", "volume"]]
