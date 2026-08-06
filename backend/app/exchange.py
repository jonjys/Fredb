"""ccxt exchange wrapper with retry/backoff, plus Real & Paper broker implementations.

Using ccxt (not a Binance-specific SDK) means adding a new exchange later is
mostly a one-line change to EXCHANGE_ID, as required.
"""
from __future__ import annotations

import abc
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

    async def close(self):
        await self.exchange.close()


@dataclass
class Fill:
    price: float
    qty: float
    fee_quote: float


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


class FuturesBroker(abc.ABC):
    @abc.abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame: ...

    @abc.abstractmethod
    async def get_price(self, symbol: str) -> float: ...

    @abc.abstractmethod
    async def get_quote_balance(self) -> float: ...

    @abc.abstractmethod
    async def open_long(
        self, symbol: str, qty: float, leverage: float, stop_loss_price: float, take_profit_price: float
    ) -> FuturesFill: ...

    @abc.abstractmethod
    async def update_stop_order(
        self, symbol: str, qty: float, old_order_id: str, new_stop_price: float
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
    async def close_long(
        self,
        symbol: str,
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

    async def get_quote_balance(self) -> float:
        return await self.client.fetch_balance_quote(self._quote_currency)

    async def open_long(
        self, symbol: str, qty: float, leverage: float, stop_loss_price: float, take_profit_price: float
    ) -> FuturesFill:
        await self.client.set_leverage(symbol, leverage)
        order = await self.client.create_market_buy(symbol, qty)
        price = float(order.get("average") or order.get("price") or 0.0)
        filled = float(order.get("filled") or qty)
        fee = _extract_fee(order)

        stop_order = await self.client.create_stop_market_order(
            symbol, "sell", filled, stop_loss_price
        )
        tp_order = await self.client.create_take_profit_market_order(
            symbol, "sell", filled, take_profit_price
        )
        return FuturesFill(
            price=price,
            qty=filled,
            fee_quote=fee,
            stop_order_id=str(stop_order.get("id", "")),
            take_profit_order_id=str(tp_order.get("id", "")),
        )

    async def update_stop_order(
        self, symbol: str, qty: float, old_order_id: str, new_stop_price: float
    ) -> str:
        if old_order_id:
            await self.client.cancel_order(old_order_id, symbol)
        new_order = await self.client.create_stop_market_order(symbol, "sell", qty, new_stop_price)
        return str(new_order.get("id", ""))

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        if order_id:
            await self.client.cancel_order(order_id, symbol)

    async def close_long(
        self,
        symbol: str,
        qty: float,
        entry_price: float,
        leverage: float,
        stop_order_id: str,
        take_profit_order_id: str,
    ) -> FuturesFill:
        for order_id in (stop_order_id, take_profit_order_id):
            if order_id:
                await self.client.cancel_order(order_id, symbol)
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

    async def get_quote_balance(self) -> float:
        return self.quote_balance

    def _simulate_fee_and_slippage(self, price: float, side: str) -> float:
        slip = self.settings.slippage_buffer_pct / 100
        return price * (1 + slip) if side == "buy" else price * (1 - slip)

    async def open_long(
        self, symbol: str, qty: float, leverage: float, stop_loss_price: float, take_profit_price: float
    ) -> FuturesFill:
        mark = await self.get_price(symbol)
        fill_price = self._simulate_fee_and_slippage(mark, "buy")
        notional = fill_price * qty
        margin_required = notional / leverage
        fee = notional * (self.settings.taker_fee_pct / 100)
        total = margin_required + fee
        if total > self.quote_balance:
            raise ValueError("Paper futures broker: insufficient simulated margin balance")
        self.quote_balance -= total
        return FuturesFill(price=fill_price, qty=qty, fee_quote=fee)

    async def update_stop_order(
        self, symbol: str, qty: float, old_order_id: str, new_stop_price: float
    ) -> str:
        return ""  # paper mode has no real orders to update; trailing is tracked in the DB row

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        pass  # paper mode has no real orders to cancel

    async def close_long(
        self,
        symbol: str,
        qty: float,
        entry_price: float,
        leverage: float,
        stop_order_id: str,
        take_profit_order_id: str,
    ) -> FuturesFill:
        mark = await self.get_price(symbol)
        fill_price = self._simulate_fee_and_slippage(mark, "sell")
        entry_notional = entry_price * qty
        exit_notional = fill_price * qty
        leveraged_pnl = exit_notional - entry_notional
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
