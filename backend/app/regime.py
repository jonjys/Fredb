# app/regime.py
"""Regime filters layered on top of the strategy signal: this symbol's own
order-book imbalance, and BTC dominance (a market-wide risk-on/risk-off
proxy no single symbol's order book can tell you).

Both fail open — a fetch error or insufficient data skips the gate rather
than blocking a trade — since these are additional filters on top of the
core signal, not infrastructure the bot should ever halt for.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from app.config import Settings

logger = logging.getLogger("tradingbot.regime")

_COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"


def orderbook_imbalance(order_book: Dict, depth_levels: int) -> Optional[float]:
    """sum(bid_qty)/sum(ask_qty) over the top `depth_levels` on each side.

    >1 means more resting size on the bid (buy pressure/support), <1 means
    more on the ask (sell pressure/resistance). None if the book doesn't
    have real depth to judge from, rather than a misleading number.
    """
    bids = order_book.get("bids") or []
    asks = order_book.get("asks") or []
    if not bids or not asks:
        return None
    bid_qty = sum(q for _, q in bids[:depth_levels])
    ask_qty = sum(q for _, q in asks[:depth_levels])
    if ask_qty <= 0:
        return None
    return bid_qty / ask_qty


def _fetch_btc_dominance_sync() -> float:
    """Synchronous by design (urllib, not a real async HTTP client) — same
    tradeoff as app/notifications.py: this is one small request every
    regime_btc_dominance_refresh_seconds (15 min default), not a hot path,
    so stdlib + asyncio.to_thread is plenty and avoids a new dependency.
    """
    req = urllib.request.Request(_COINGECKO_GLOBAL_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        payload = json.loads(resp.read())
    return float(payload["data"]["market_cap_percentage"]["btc"])


class BtcDominanceTracker:
    """Polls CoinGecko's free, no-key /api/v3/global endpoint for BTC's
    share of total crypto market cap and keeps a short rolling history so
    callers can ask "how much has dominance moved in the last hour" — a
    slow-moving macro signal, not something that needs per-tick freshness.

    Intended to be shared as a module-level singleton between the spot and
    futures bots (see btc_dominance_tracker below) so both draw from one
    poll instead of doubling CoinGecko's free-tier rate limit.
    """

    def __init__(self) -> None:
        self._history: List[Tuple[float, float]] = []  # (timestamp, btc_dominance_pct)

    async def get_change_1h_pct(self, refresh_seconds: float) -> Optional[float]:
        """Change in BTC dominance (percentage points) over roughly the
        last hour, or None if there isn't enough history yet or the last
        refresh failed. Callers must treat None as "skip this gate," never
        as a value of zero.
        """
        await self._maybe_refresh(refresh_seconds)
        if len(self._history) < 2:
            return None
        _now_ts, now_dom = self._history[-1]
        cutoff = time.time() - 3600
        past_dom = None
        for ts, dom in self._history:
            if ts <= cutoff:
                past_dom = dom
            else:
                break
        if past_dom is None:
            return None
        return now_dom - past_dom

    async def _maybe_refresh(self, refresh_seconds: float) -> None:
        now = time.time()
        if self._history and now - self._history[-1][0] < refresh_seconds:
            return
        try:
            dominance = await asyncio.to_thread(_fetch_btc_dominance_sync)
        except Exception:
            logger.warning(
                "Failed to refresh BTC dominance — regime gate skipped until next refresh", exc_info=True
            )
            return
        self._history.append((now, dominance))
        # ~2h of samples is comfortably more than the 1h lookback needs.
        cutoff = now - 7200
        self._history = [(ts, d) for ts, d in self._history if ts >= cutoff]


btc_dominance_tracker = BtcDominanceTracker()


async def regime_block_reason(broker: Any, symbol: str, side: str, settings: Settings) -> Optional[str]:
    """None if `side` ("long"/"short") clears both regime gates for `symbol`,
    else a short human-readable reason it didn't — for skip-logging.

    Both gates fail open: a broker/order-book fetch error or a BTC
    dominance read with insufficient history skips that gate rather than
    blocking the trade, since a regime filter going dark shouldn't itself
    become a reason no positions ever open.
    """
    try:
        book = await broker.get_order_book(symbol, settings.regime_orderbook_depth_levels)
        imbalance = orderbook_imbalance(book, settings.regime_orderbook_depth_levels)
    except Exception:
        logger.warning("Failed to fetch order book for %s regime check — gate skipped", symbol, exc_info=True)
        imbalance = None

    if imbalance is not None:
        min_imbalance = settings.regime_orderbook_imbalance_min
        if side == "long" and imbalance < min_imbalance:
            return f"orderbook imbalance {imbalance:.2f}<{min_imbalance:.2f} (ask-heavy)"
        if side == "short" and min_imbalance > 0 and imbalance > 1 / min_imbalance:
            return f"orderbook imbalance {imbalance:.2f}>{1 / min_imbalance:.2f} (bid-heavy)"

    if settings.regime_btc_dominance_enabled:
        change_pct = await btc_dominance_tracker.get_change_1h_pct(settings.regime_btc_dominance_refresh_seconds)
        if change_pct is not None:
            threshold = settings.regime_btc_dominance_move_threshold_pct
            if side == "long" and change_pct > threshold:
                return f"BTC.D +{change_pct:.2f}pp/1h (capital rotating into BTC, risk-off for alts)"
            if side == "short" and change_pct < -threshold:
                return f"BTC.D {change_pct:.2f}pp/1h (capital rotating into alts, risk-on)"

    return None
