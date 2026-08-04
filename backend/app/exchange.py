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

    def __init__(self, settings: Settings, use_credentials: bool):
        exchange_class = getattr(ccxt_async, settings.exchange_id)
        config: Dict = {"enableRateLimit": True}
        if use_credentials:
            config["apiKey"] = settings.exchange_api_key
            config["secret"] = settings.exchange_api_secret
            if settings.exchange_id == "coinbase" and settings.coinbase_password:
                config["password"] = settings.coinbase_password
        self.exchange = exchange_class(config)
        if settings.bot_mode == "testnet" and use_credentials:
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
