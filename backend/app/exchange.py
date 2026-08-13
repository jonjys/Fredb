# app/exchange.py
"""ccxt exchange wrapper with retry/backoff, plus Real & Paper broker implementations.

Using ccxt (not a Binance-specific SDK) means adding a new exchange later is
mostly a one-line change to EXCHANGE_ID, as required.
"""
from __future__ import annotations

import abc
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import ccxt.async_support as ccxt_async
import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings

logger = logging.getLogger("tradingbot.exchange")

RETRYABLE = (
    ccxt_async.NetworkError,
    ccxt_async.ExchangeNotAvailable,
    ccxt_async.RequestTimeout,
    ccxt_async.DDoSProtection,
)


def _retry():
    return retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(RETRYABLE),
        before_sleep=lambda s: logger.warning(
            "Exchange call failed (attempt %s), retrying: %s",
            s.attempt_number,
            s.outcome.exception(),
        ),
    )


# Binance's USDT-M futures also list tokenized-equity/commodity perpetuals
# (tokenized stocks, tokenized gold, leveraged-ETF tokens, ...) as plain
# linear USDT swaps — structurally indistinguishable from a crypto
# perpetual in ccxt's unified market fields (same swap/linear/quote flags),
# and observed tickers like HEI/SPCX/SNDK/XAU/SOXL/MU/SKHYNIX/KORU don't
# read as obviously non-crypto by name either. Two different attempts at
# telling them apart algorithmically both failed in practice: cross-
# referencing Binance's own spot listings (some of these are spot-listed on
# Binance too) and cross-referencing CoinGecko's coin list (CoinGecko
# tracks tokenized-RWA products as "crypto" too, plus its category system
# doesn't line up with Binance's specific ticker naming). An allowlist is
# the fix that's actually reliable: only trade base assets on this curated
# list of well-established cryptocurrencies. It costs some coverage (a
# brand-new legitimate coin needs to be added here manually), but a dynamic
# scan that occasionally misses a new coin is a far smaller problem than
# one that occasionally leverage-trades tokenized gold or SpaceX stock.
# Extend via the FUTURES_EXTRA_ALLOWED_SYMBOLS env var, not by loosening
# this filter's logic.
KNOWN_CRYPTO_BASE_ASSETS = frozenset(
    {
        # Majors / large-cap L1s
        "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "AVAX", "DOT",
        "LINK", "MATIC", "POL", "LTC", "BCH", "TON", "NEAR", "ICP", "APT", "SUI",
        "ATOM", "XLM", "XMR", "ETC", "FIL", "ARB", "OP", "HBAR", "VET", "ALGO",
        "SEI", "TIA", "INJ", "KAS", "STX", "FTM", "EGLD", "FLOW", "KDA", "CFX",
        "NEO", "IOTA", "ONT", "ZIL", "QTUM", "WAVES", "KSM", "ROSE", "CELO",
        "ONE", "ANKR", "OMG", "ZRX", "ENJ",
        # DeFi
        "UNI", "AAVE", "MKR", "GRT", "CRV", "SNX", "COMP", "YFI", "SUSHI",
        "1INCH", "BAL", "LDO", "RPL", "FXS", "PENDLE", "ENS", "DYDX", "GMX",
        "WOO", "CAKE", "QNT", "GMT",
        # Gaming / metaverse / AI
        "SAND", "MANA", "AXS", "GALA", "IMX", "APE", "THETA", "CHZ", "MASK",
        "FET", "AGIX", "OCEAN", "RENDER", "RNDR", "WLD", "PYTH", "JTO", "JUP",
        # Meme / high-volatility (explicitly requested — real volume required
        # via the liquidity floor regardless)
        "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "BOME", "MEME", "MEW",
        "POPCAT", "BRETT", "TURBO", "MOG", "NEIRO", "PNUT", "GOAT", "ACT",
        "ORDI", "SATS", "DOGS", "NOT",
        # Established mid-caps
        "EOS", "XTZ", "DASH", "ZEC", "RUNE", "KAVA", "BAT", "HOT", "DENT",
        "IOST", "WIN", "COTI", "SKL", "STORJ", "OGN", "BAND", "REN", "KNC",
        "LRC", "CVC", "POWR", "REQ", "STMX", "CTSI", "AR", "ROSE", "GLMR",
        "MOVR", "ASTR", "MINA", "CELR", "SXP", "ALPHA", "TWT",
    }
)


def _load_extra_allowed_symbols(settings: Settings) -> frozenset:
    extra = getattr(settings, "futures_extra_allowed_symbols_csv", "") or ""
    return frozenset(s.strip().upper() for s in extra.split(",") if s.strip())


class ExchangeClient:
    """Thin, retrying async wrapper around a ccxt exchange instance.

    Used both for real trading (testnet/live) and, in paper mode, purely to
    fetch real public market data (no keys required) to mark simulated fills.
    """

    def __init__(
        self,
        settings: Settings,
        use_credentials: bool,
        exchange_id: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        exchange_id = exchange_id or settings.exchange_id
        mode = mode or settings.bot_mode
        exchange_class = getattr(ccxt_async, exchange_id)
        config: Dict = {"enableRateLimit": True}
        if use_credentials:
            config["apiKey"] = settings.exchange_api_key
            config["secret"] = settings.exchange_api_secret
            if settings.exchange_id == "coinbase" and settings.coinbase_password:
                config["password"] = settings.coinbase_password
        self.exchange = exchange_class(config)
        if mode == "testnet" and use_credentials:
            self.exchange.set_sandbox_mode(True)
        self.settings = settings

    @_retry()
    async def load_markets(self):
        return await self.exchange.load_markets()

    @_retry()
    async def fetch_ohlcv_df(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        raw = await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        return df

    @_retry()
    async def fetch_ticker_price(self, symbol: str) -> float:
        ticker = await self.exchange.fetch_ticker(symbol)
        return float(ticker["last"])

    @_retry()
    async def fetch_top_symbols_by_volume(
        self, quote: str, top_n: int, min_volume_usd: float
    ) -> List[str]:
        """Linear USDT-margined *cryptocurrency* perpetual swaps only,
        ranked by 24h quote volume, above a liquidity floor. This is how the
        futures bot finds tradeable pairs beyond a fixed BTC/ETH list
        without ending up scanning (and risking leveraged capital on) thin,
        easily-manipulated markets — a bot picking symbols with real volume
        behind them is very different from a bot picking symbols by name.

        Also excludes tokenized-stock/commodity perpetuals (e.g. tokenized
        equities, gold) that Binance lists under the same linear-USDT-swap
        market shape as crypto — see KNOWN_CRYPTO_BASE_ASSETS.
        """
        await self.exchange.load_markets()
        allowed_bases = KNOWN_CRYPTO_BASE_ASSETS | _load_extra_allowed_symbols(self.settings)
        tickers = await self.exchange.fetch_tickers()
        candidates = []
        for symbol, ticker in tickers.items():
            market = self.exchange.markets.get(symbol)
            if not market or not market.get("swap") or not market.get("linear"):
                continue
            if market.get("quote") != quote:
                continue
            if not market.get("active", True):
                continue
            base = market.get("base") or ""
            if base.upper() not in allowed_bases:
                continue
            quote_volume = ticker.get("quoteVolume") or 0
            if quote_volume < min_volume_usd:
                continue
            candidates.append((symbol, quote_volume))
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return [symbol for symbol, _ in candidates[:top_n]]

    @_retry()
    async def fetch_balance_quote(self, quote_currency: str) -> float:
        balance = await self.exchange.fetch_balance()
        return float(balance.get("free", {}).get(quote_currency, 0.0))

    @_retry()
    async def create_market_buy(self, symbol: str, qty: float):
        return await self.exchange.create_market_buy_order(symbol, qty)

    @_retry()
    async def create_market_sell(self, symbol: str, qty: float):
        return await self.exchange.create_market_sell_order(symbol, qty)

    @_retry()
    async def set_leverage(self, symbol: str, leverage: float):
        return await self.exchange.set_leverage(int(leverage), symbol)

    @_retry()
    async def create_stop_market_order(self, symbol: str, side: str, qty: float, stop_price: float):
        """reduceOnly stop-market order — the exchange-native, latency-free
        protection that fires even if this process is down or slow."""
        return await self.exchange.create_order(
            symbol,
            "STOP_MARKET",
            side,
            qty,
            params={"stopPrice": stop_price, "reduceOnly": True},
        )

    @_retry()
    async def create_take_profit_market_order(
        self, symbol: str, side: str, qty: float, stop_price: float
    ):
        return await self.exchange.create_order(
            symbol,
            "TAKE_PROFIT_MARKET",
            side,
            qty,
            params={"stopPrice": stop_price, "reduceOnly": True},
        )

    @_retry()
    async def cancel_order(self, order_id: str, symbol: str):
        try:
            return await self.exchange.cancel_order(order_id, symbol)
        except ccxt_async.OrderNotFound:
            return None

    @_retry()
    async def fetch_order_book_top(self, symbol: str) -> "tuple[float, float]":
        """Best bid/ask, for pricing a post-only limit order — placing at the
        touch (not crossing the spread) is what makes it a maker order."""
        book = await self.exchange.fetch_order_book(symbol, limit=5)
        best_bid = float(book["bids"][0][0]) if book.get("bids") else 0.0
        best_ask = float(book["asks"][0][0]) if book.get("asks") else 0.0
        return best_bid, best_ask

    @_retry()
    async def fetch_order_book_depth(self, symbol: str, limit: int = 15) -> Dict:
        """Multi-level order book for the market-view UI — a deeper read than
        fetch_order_book_top, which only needs the touch price. Public data,
        no credentials required, so this works in paper mode too."""
        book = await self.exchange.fetch_order_book(symbol, limit=limit)
        bids = [[float(p), float(q)] for p, q in (book.get("bids") or [])[:limit]]
        asks = [[float(p), float(q)] for p, q in (book.get("asks") or [])[:limit]]
        return {"bids": bids, "asks": asks}

    @_retry()
    async def create_post_only_limit(self, symbol: str, side: str, qty: float, price: float):
        """GTX (good-till-crossing) tells Binance to reject the order outright
        rather than fill it as a taker if it would cross the spread — the
        exchange enforces "maker or nothing" for us, so there's no client-side
        race where this quietly becomes a taker fill."""
        return await self.exchange.create_order(
            symbol, "limit", side, qty, price,
            params={"postOnly": True, "timeInForce": "GTX"},
        )

    @_retry()
    async def fetch_order(self, order_id: str, symbol: str):
        return await self.exchange.fetch_order(order_id, symbol)

    async def close(self):
        await self.exchange.close()


async def wait_for_fill_or_cancel(
    client: "ExchangeClient",
    order_id: str,
    symbol: str,
    timeout_seconds: float,
    poll_interval_seconds: float = 1.0,
):
    """Poll a resting post-only order until it fills or the timeout elapses,
    then cancel whatever's left. Returns the final order dict if anything
    filled (fully or partially), else None — the caller re-evaluates the
    signal fresh next tick rather than chasing price with a wider order.

    This is the "never chase the price aggressively" rule from the spec,
    implemented literally: on timeout we cancel and walk away, we do not
    place a marketable order to force a fill.
    """
    elapsed = 0.0
    while elapsed < timeout_seconds:
        await asyncio.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds
        try:
            order = await client.fetch_order(order_id, symbol)
        except Exception:
            logger.exception("Failed to poll post-only order %s (%s)", order_id, symbol)
            continue
        if order.get("status") == "closed":
            return order

    try:
        await client.cancel_order(order_id, symbol)
    except Exception:
        logger.exception("Failed to cancel unfilled post-only order %s (%s)", order_id, symbol)

    # A fill can race the cancel (order fills the instant before the cancel
    # lands) — re-check once so a real fill is never silently dropped.
    try:
        final = await client.fetch_order(order_id, symbol)
        if float(final.get("filled") or 0) > 0:
            return final
    except Exception:
        logger.exception("Failed to re-check post-only order %s (%s) after cancel", order_id, symbol)
    return None


async def place_post_only_with_retries(
    client: "ExchangeClient",
    symbol: str,
    side: str,
    qty: float,
    timeout_seconds: float,
    poll_interval_seconds: float,
    max_retries: int,
) -> "tuple[Optional[dict], int]":
    """Place a postOnly/GTX limit at the current touch price. On timeout,
    cancel and repost at a *fresh* touch price — the market may have moved
    since the first quote — up to max_retries additional attempts. Every
    attempt is still GTX, so this never crosses the spread to force a fill;
    it only refreshes a stale price instead of giving up after one try.

    Returns (filled_order_dict_or_None, retries_used).
    """
    attempts = max_retries + 1
    for attempt in range(attempts):
        best_bid, best_ask = await client.fetch_order_book_top(symbol)
        price = best_bid if side == "buy" else best_ask
        if price <= 0:
            return None, attempt
        order = await client.create_post_only_limit(symbol, side, qty, price)
        order_id = str(order.get("id", ""))
        filled = await wait_for_fill_or_cancel(client, order_id, symbol, timeout_seconds, poll_interval_seconds)
        if filled is not None and float(filled.get("filled") or 0) > 0:
            return filled, attempt
    return None, attempts - 1


@dataclass
class Fill:
    price: float
    qty: float
    fee_quote: float
    retries_used: int = 0


class Broker(abc.ABC):
    """Unified interface used by the bot, regardless of paper/testnet/live."""

    @abc.abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame: ...

    @abc.abstractmethod
    async def get_price(self, symbol: str) -> float: ...

    @abc.abstractmethod
    async def get_quote_balance(self) -> float: ...

    @abc.abstractmethod
    async def buy(self, symbol: str, qty: float) -> Fill: ...

    @abc.abstractmethod
    async def sell(self, symbol: str, qty: float) -> Fill: ...

    async def close(self) -> None:
        pass


class RealBroker(Broker):
    """Executes real orders against testnet or live exchange via ccxt."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = ExchangeClient(settings, use_credentials=True)
        self._quote_currency = "USDT"

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        return await self.client.fetch_ohlcv_df(symbol, timeframe, limit)

    async def get_price(self, symbol: str) -> float:
        return await self.client.fetch_ticker_price(symbol)

    async def get_order_book(self, symbol: str, limit: int = 15) -> Dict:
        return await self.client.fetch_order_book_depth(symbol, limit)

    async def get_quote_balance(self) -> float:
        return await self.client.fetch_balance_quote(self._quote_currency)

    async def buy(self, symbol: str, qty: float) -> Fill:
        order = await self.client.create_market_buy(symbol, qty)
        price = float(order.get("average") or order.get("price") or 0.0)
        filled = float(order.get("filled") or qty)
        fee = _extract_fee(order)
        return Fill(price=price, qty=filled, fee_quote=fee)

    async def sell(self, symbol: str, qty: float) -> Fill:
        order = await self.client.create_market_sell(symbol, qty)
        price = float(order.get("average") or order.get("price") or 0.0)
        filled = float(order.get("filled") or qty)
        fee = _extract_fee(order)
        return Fill(price=price, qty=filled, fee_quote=fee)

    async def _post_only(self, symbol: str, side: str, qty: float, timeout_seconds: Optional[float]) -> Optional[Fill]:
        timeout_seconds = timeout_seconds if timeout_seconds is not None else self.settings.post_only_timeout_seconds
        filled, retries_used = await place_post_only_with_retries(
            self.client, symbol, side, qty, timeout_seconds,
            self.settings.post_only_poll_interval_seconds, self.settings.post_only_max_retries,
        )
        if filled is None:
            return None
        fill_price = float(filled.get("average") or filled.get("price") or 0.0)
        qty_filled = float(filled.get("filled") or 0.0)
        if qty_filled <= 0 or fill_price <= 0:
            return None
        return Fill(price=fill_price, qty=qty_filled, fee_quote=_extract_fee(filled), retries_used=retries_used)

    async def buy_post_only(self, symbol: str, qty: float, timeout_seconds: Optional[float] = None) -> Optional[Fill]:
        """Entry-only: places at the best bid with postOnly/GTX so it can
        only ever fill as a maker. Returns None (never a market fallback) if
        it isn't filled within timeout_seconds — see wait_for_fill_or_cancel."""
        return await self._post_only(symbol, "buy", qty, timeout_seconds)

    async def sell_post_only(self, symbol: str, qty: float, timeout_seconds: Optional[float] = None) -> Optional[Fill]:
        return await self._post_only(symbol, "sell", qty, timeout_seconds)

    async def close(self) -> None:
        await self.client.close()


def _extract_fee(order: dict) -> float:
    fee = order.get("fee") or {}
    if fee:
        return float(fee.get("cost") or 0.0)
    fees = order.get("fees") or []
    return sum(float(f.get("cost") or 0.0) for f in fees)


class PaperBroker(Broker):
    """Simulates a wallet & fills against real public market data.

    No API keys required. This is the safe default and should be used until
    the strategy has proven itself.
    """

    def __init__(self, settings: Settings, starting_balance: float):
        self.settings = settings
        # public-data-only client, no credentials needed
        self.client = ExchangeClient(settings, use_credentials=False)
        self.quote_balance = starting_balance
        self.base_holdings: Dict[str, float] = {}

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        return await self.client.fetch_ohlcv_df(symbol, timeframe, limit)

    async def get_price(self, symbol: str) -> float:
        return await self.client.fetch_ticker_price(symbol)

    async def get_order_book(self, symbol: str, limit: int = 15) -> Dict:
        return await self.client.fetch_order_book_depth(symbol, limit)

    async def get_quote_balance(self) -> float:
        return self.quote_balance

    def _simulate_fee_and_slippage(self, price: float, side: str) -> float:
        slip = self.settings.slippage_buffer_pct / 100
        return price * (1 + slip) if side == "buy" else price * (1 - slip)

    async def buy(self, symbol: str, qty: float) -> Fill:
        mark = await self.get_price(symbol)
        fill_price = self._simulate_fee_and_slippage(mark, "buy")
        cost = fill_price * qty
        fee = cost * (self.settings.taker_fee_pct / 100)
        total = cost + fee
        if total > self.quote_balance:
            raise ValueError("Paper broker: insufficient simulated balance")
        self.quote_balance -= total
        self.base_holdings[symbol] = self.base_holdings.get(symbol, 0.0) + qty
        return Fill(price=fill_price, qty=qty, fee_quote=fee)

    async def sell(self, symbol: str, qty: float) -> Fill:
        mark = await self.get_price(symbol)
        fill_price = self._simulate_fee_and_slippage(mark, "sell")
        proceeds = fill_price * qty
        fee = proceeds * (self.settings.taker_fee_pct / 100)
        net = proceeds - fee
        self.quote_balance += net
        self.base_holdings[symbol] = max(0.0, self.base_holdings.get(symbol, 0.0) - qty)
        return Fill(price=fill_price, qty=qty, fee_quote=fee)

    # Paper mode has no real order book depth or latency to simulate a
    # partial/no-fill against, so a post-only order fills immediately at the
    # best bid/ask — zero slippage (the actual economic benefit of a maker
    # order) at the maker fee rate. That's optimistic versus a real exchange,
    # where a post-only order can go unfilled and get cancelled — which is
    # exactly why the timeout/re-price path in RealBroker still matters once
    # this graduates to testnet/live.
    async def buy_post_only(self, symbol: str, qty: float, timeout_seconds: Optional[float] = None) -> Optional[Fill]:
        best_bid, _ = await self.client.fetch_order_book_top(symbol)
        price = best_bid or await self.get_price(symbol)
        cost = price * qty
        fee = cost * (self.settings.maker_fee_pct / 100)
        total = cost + fee
        if total > self.quote_balance:
            raise ValueError("Paper broker: insufficient simulated balance")
        self.quote_balance -= total
        self.base_holdings[symbol] = self.base_holdings.get(symbol, 0.0) + qty
        return Fill(price=price, qty=qty, fee_quote=fee)

    async def sell_post_only(self, symbol: str, qty: float, timeout_seconds: Optional[float] = None) -> Optional[Fill]:
        _, best_ask = await self.client.fetch_order_book_top(symbol)
        price = best_ask or await self.get_price(symbol)
        proceeds = price * qty
        fee = proceeds * (self.settings.maker_fee_pct / 100)
        self.quote_balance += proceeds - fee
        self.base_holdings[symbol] = max(0.0, self.base_holdings.get(symbol, 0.0) - qty)
        return Fill(price=price, qty=qty, fee_quote=fee)

    async def close(self) -> None:
        await self.client.close()


def build_broker(settings: Settings) -> Broker:
    if settings.bot_mode == "paper":
        return PaperBroker(settings, settings.paper_starting_balance)
    return RealBroker(settings)


# ---------------------------------------------------------------------------
# Futures (leveraged) trading
#
# Deliberately a separate interface from Broker above, not a subclass: entry
# and exit here involve leverage and exchange-native stop/take-profit orders
# (STOP_MARKET/TAKE_PROFIT_MARKET, reduceOnly) rather than plain market buy
# and poll-only exits. Placing the stop/TP as real orders at entry time,
# instead of only checking price on our poll loop, matters specifically
# because leverage makes the liquidation distance small — a soft, polled
# stop can lose a race with a fast move between poll ticks; an exchange-side
# order can't.
# ---------------------------------------------------------------------------


@dataclass
class FuturesFill:
    price: float
    qty: float
    fee_quote: float
    stop_order_id: str = ""
    take_profit_order_id: str = ""
    retries_used: int = 0


class FuturesBroker(abc.ABC):
    @abc.abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame: ...

    @abc.abstractmethod
    async def get_price(self, symbol: str) -> float: ...

    @abc.abstractmethod
    async def get_quote_balance(self) -> float: ...

    @abc.abstractmethod
    async def get_top_symbols(self, top_n: int, min_volume_usd: float) -> List[str]:
        """Discover a tradeable symbol universe by 24h volume, instead of a
        fixed list — see ExchangeClient.fetch_top_symbols_by_volume."""
        ...

    @abc.abstractmethod
    async def open_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        leverage: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> FuturesFill:
        """side is "long" or "short". A long enters with a market buy and is
        protected by sell-side stop/TP orders; a short is the exact mirror
        (market sell in, buy-side stop above / TP below)."""
        ...

    @abc.abstractmethod
    async def update_stop_order(
        self, symbol: str, side: str, qty: float, old_order_id: str, new_stop_price: float
    ) -> str:
        """Cancel the existing stop order (if any) and place a new one at the
        updated trailing-stop price. Returns the new order id."""
        ...

    @abc.abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> None:
        """Cancel a standalone order (e.g. the fixed take-profit order once
        trailing-stop mode takes over). No-op for an empty/already-gone id."""
        ...

    @abc.abstractmethod
    async def close_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        leverage: float,
        stop_order_id: str,
        take_profit_order_id: str,
    ) -> FuturesFill:
        """entry_price/leverage are unused by the real broker (the exchange
        settles margin/PnL itself) but kept in the shared signature so the
        paper broker can reconstruct locked margin + leveraged PnL without a
        second, divergent interface."""
        ...

    async def close(self) -> None:
        pass


def _exit_side(position_side: str) -> str:
    """The order side that reduces/closes a position: sell out of a long,
    buy back a short. Used for the protective stop, the take-profit, and
    the final exit alike."""
    return "buy" if position_side == "short" else "sell"


class RealFuturesBroker(FuturesBroker):
    """Executes real leveraged orders against Binance USDT-M futures
    (testnet or live) via ccxt's binanceusdm."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = ExchangeClient(
            settings,
            use_credentials=True,
            exchange_id=settings.futures_exchange_id,
            mode=settings.futures_mode,
        )
        self._quote_currency = "USDT"

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        return await self.client.fetch_ohlcv_df(symbol, timeframe, limit)

    async def get_price(self, symbol: str) -> float:
        return await self.client.fetch_ticker_price(symbol)

    async def get_order_book(self, symbol: str, limit: int = 15) -> Dict:
        return await self.client.fetch_order_book_depth(symbol, limit)

    async def get_quote_balance(self) -> float:
        return await self.client.fetch_balance_quote(self._quote_currency)

    async def get_top_symbols(self, top_n: int, min_volume_usd: float) -> List[str]:
        return await self.client.fetch_top_symbols_by_volume(
            self._quote_currency, top_n, min_volume_usd
        )

    async def open_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        leverage: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> FuturesFill:
        await self.client.set_leverage(symbol, leverage)
        if side == "short":
            order = await self.client.create_market_sell(symbol, qty)
        else:
            order = await self.client.create_market_buy(symbol, qty)
        price = float(order.get("average") or order.get("price") or 0.0)
        filled = float(order.get("filled") or qty)
        fee = _extract_fee(order)

        exit_side = _exit_side(side)
        stop_order = await self.client.create_stop_market_order(
            symbol, exit_side, filled, stop_loss_price
        )
        tp_order = await self.client.create_take_profit_market_order(
            symbol, exit_side, filled, take_profit_price
        )
        return FuturesFill(
            price=price,
            qty=filled,
            fee_quote=fee,
            stop_order_id=str(stop_order.get("id", "")),
            take_profit_order_id=str(tp_order.get("id", "")),
        )

    async def open_position_post_only(
        self,
        symbol: str,
        side: str,
        qty: float,
        leverage: float,
        stop_loss_price: float,
        take_profit_price: float,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[FuturesFill]:
        """Same protective-order behavior as open_position, but the entry
        itself is a postOnly/GTX limit at the current best bid (long) / best
        ask (short) instead of a market order. Returns None — placing no
        position at all — if it isn't filled within timeout_seconds; the
        stop/TP orders are only placed once an actual fill exists, so there
        is never a dangling protective order with nothing to protect."""
        timeout_seconds = timeout_seconds if timeout_seconds is not None else self.settings.post_only_timeout_seconds
        await self.client.set_leverage(symbol, leverage)
        order_side = "sell" if side == "short" else "buy"
        filled, retries_used = await place_post_only_with_retries(
            self.client, symbol, order_side, qty, timeout_seconds,
            self.settings.post_only_poll_interval_seconds, self.settings.post_only_max_retries,
        )
        if filled is None:
            return None
        fill_price = float(filled.get("average") or filled.get("price") or 0.0)
        filled_qty = float(filled.get("filled") or 0.0)
        if filled_qty <= 0 or fill_price <= 0:
            return None
        fee = _extract_fee(filled)

        exit_side = _exit_side(side)
        stop_order = await self.client.create_stop_market_order(symbol, exit_side, filled_qty, stop_loss_price)
        tp_order = await self.client.create_take_profit_market_order(symbol, exit_side, filled_qty, take_profit_price)
        return FuturesFill(
            price=fill_price,
            qty=filled_qty,
            fee_quote=fee,
            stop_order_id=str(stop_order.get("id", "")),
            take_profit_order_id=str(tp_order.get("id", "")),
            retries_used=retries_used,
        )

    async def update_stop_order(
        self, symbol: str, side: str, qty: float, old_order_id: str, new_stop_price: float
    ) -> str:
        if old_order_id:
            await self.client.cancel_order(old_order_id, symbol)
        new_order = await self.client.create_stop_market_order(
            symbol, _exit_side(side), qty, new_stop_price
        )
        return str(new_order.get("id", ""))

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        if order_id:
            await self.client.cancel_order(order_id, symbol)

    async def close_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        leverage: float,
        stop_order_id: str,
        take_profit_order_id: str,
    ) -> FuturesFill:
        for order_id in (stop_order_id, take_profit_order_id):
            if order_id:
                await self.client.cancel_order(order_id, symbol)
        if side == "short":
            order = await self.client.create_market_buy(symbol, qty)
        else:
            order = await self.client.create_market_sell(symbol, qty)
        price = float(order.get("average") or order.get("price") or 0.0)
        filled = float(order.get("filled") or qty)
        fee = _extract_fee(order)
        return FuturesFill(price=price, qty=filled, fee_quote=fee)

    async def close(self) -> None:
        await self.client.close()


class PaperFuturesBroker(FuturesBroker):
    """Simulates a leveraged wallet against real public market data. No API
    keys required. Stop/take-profit are NOT placed as real orders here (there
    is no real exchange position to attach them to) — the bot's poll loop
    manages exits the same way the spot paper broker does. That's fine: paper
    mode has no real money and therefore no liquidation-race risk to guard
    against in the first place.
    """

    def __init__(self, settings: Settings, starting_balance: float):
        self.settings = settings
        self.client = ExchangeClient(
            settings, use_credentials=False, exchange_id=settings.futures_exchange_id
        )
        self.quote_balance = starting_balance

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        return await self.client.fetch_ohlcv_df(symbol, timeframe, limit)

    async def get_price(self, symbol: str) -> float:
        return await self.client.fetch_ticker_price(symbol)

    async def get_order_book(self, symbol: str, limit: int = 15) -> Dict:
        return await self.client.fetch_order_book_depth(symbol, limit)

    async def get_quote_balance(self) -> float:
        return self.quote_balance

    async def get_top_symbols(self, top_n: int, min_volume_usd: float) -> List[str]:
        return await self.client.fetch_top_symbols_by_volume("USDT", top_n, min_volume_usd)

    def _simulate_fee_and_slippage(self, price: float, side: str) -> float:
        slip = self.settings.slippage_buffer_pct / 100
        return price * (1 + slip) if side == "buy" else price * (1 - slip)

    async def open_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        leverage: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> FuturesFill:
        mark = await self.get_price(symbol)
        # Slippage always works against you: you buy a touch high and sell a
        # touch low, whichever direction you're opening in.
        fill_price = self._simulate_fee_and_slippage(mark, "sell" if side == "short" else "buy")
        notional = fill_price * qty
        margin_required = notional / leverage
        fee = notional * (self.settings.taker_fee_pct / 100)
        total = margin_required + fee
        if total > self.quote_balance:
            raise ValueError("Paper futures broker: insufficient simulated margin balance")
        self.quote_balance -= total
        return FuturesFill(price=fill_price, qty=qty, fee_quote=fee)

    async def open_position_post_only(
        self,
        symbol: str,
        side: str,
        qty: float,
        leverage: float,
        stop_loss_price: float,
        take_profit_price: float,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[FuturesFill]:
        """Paper-mode approximation: fills immediately at the best bid/ask
        (zero slippage) with the maker fee, same simplification and caveat
        as PaperBroker.buy_post_only above."""
        best_bid, best_ask = await self.client.fetch_order_book_top(symbol)
        order_side = "sell" if side == "short" else "buy"
        price = (best_bid if order_side == "buy" else best_ask) or await self.get_price(symbol)
        notional = price * qty
        margin_required = notional / leverage
        fee = notional * (self.settings.maker_fee_pct / 100)
        total = margin_required + fee
        if total > self.quote_balance:
            raise ValueError("Paper futures broker: insufficient simulated margin balance")
        self.quote_balance -= total
        return FuturesFill(price=price, qty=qty, fee_quote=fee)

    async def update_stop_order(
        self, symbol: str, side: str, qty: float, old_order_id: str, new_stop_price: float
    ) -> str:
        return ""  # paper mode has no real orders to update; trailing is tracked in the DB row

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        pass  # paper mode has no real orders to cancel

    async def close_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        leverage: float,
        stop_order_id: str,
        take_profit_order_id: str,
    ) -> FuturesFill:
        mark = await self.get_price(symbol)
        fill_price = self._simulate_fee_and_slippage(mark, "buy" if side == "short" else "sell")
        entry_notional = entry_price * qty
        exit_notional = fill_price * qty
        # A short profits when the exit price is BELOW entry, so the sign of
        # the price move flips relative to a long.
        leveraged_pnl = (
            entry_notional - exit_notional if side == "short" else exit_notional - entry_notional
        )
        margin_locked = entry_notional / leverage
        fee = exit_notional * (self.settings.taker_fee_pct / 100)
        # Return the locked margin plus the (leveraged) price PnL, minus the
        # exit fee. Funding-rate cost is not simulated — a known
        # simplification of paper mode, immaterial for short scalping holds.
        self.quote_balance += margin_locked + leveraged_pnl - fee
        return FuturesFill(price=fill_price, qty=qty, fee_quote=fee)

    async def close(self) -> None:
        await self.client.close()


def build_futures_broker(settings: Settings) -> FuturesBroker:
    if settings.futures_mode == "paper":
        return PaperFuturesBroker(settings, settings.futures_paper_starting_balance)
    return RealFuturesBroker(settings)
