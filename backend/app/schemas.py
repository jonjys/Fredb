"""Pydantic response/request schemas for the dashboard API."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class StatusResponse(BaseModel):
    mode: str
    exchange: str
    symbols: List[str]
    running: bool
    kill_switch: bool
    kill_switch_reason: str
    equity: float
    quote_balance: float
    daily_start_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    open_positions_count: int
    max_concurrent_positions: int


class PositionOut(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    entry_price: float
    qty: float
    stop_loss_price: float
    take_profit_price: float
    trailing_active: bool
    trailing_high: float
    current_price: Optional[float] = None
    unrealized_pnl_quote: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    opened_at: float

    class Config:
        from_attributes = True


class TradeOut(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    entry_price: float
    exit_price: float
    qty: float
    pnl_quote: float
    pnl_pct: float
    close_reason: str
    opened_at: float
    closed_at: float

    class Config:
        from_attributes = True


class LogEntryOut(BaseModel):
    timestamp: float
    level: str
    message: str


class SettingsOut(BaseModel):
    max_risk_per_trade_pct: float
    max_concurrent_positions: int
    take_profit_pct: float
    trailing_stop_pct: float
    stop_loss_pct: float
    atr_multiplier: float
    max_daily_loss_pct: float
    taker_fee_pct: float
    slippage_buffer_pct: float
    poll_interval_seconds: float


class SettingsUpdate(BaseModel):
    max_risk_per_trade_pct: Optional[float] = None
    max_concurrent_positions: Optional[int] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    atr_multiplier: Optional[float] = None
    max_daily_loss_pct: Optional[float] = None
    taker_fee_pct: Optional[float] = None
    slippage_buffer_pct: Optional[float] = None
    poll_interval_seconds: Optional[float] = None


class EquityPointOut(BaseModel):
    timestamp: float
    equity: float
    realized_pnl_today: float


# ---- Futures --------------------------------------------------------------


class FuturesStatusResponse(BaseModel):
    enabled: bool
    mode: str
    exchange: str
    symbols: List[str]
    running: bool
    kill_switch: bool
    kill_switch_reason: str
    equity: float
    quote_balance: float
    daily_start_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    open_positions_count: int
    max_concurrent_positions: int
    leverage_default: float
    leverage_mode: str
    max_leverage: float
    auto_leverage_min: float
    auto_leverage_max: float


class FuturesPositionOut(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    leverage: float
    entry_price: float
    qty: float
    margin_used: float
    liquidation_price: float
    stop_loss_price: float
    take_profit_price: float
    trailing_active: bool
    trailing_high: float
    current_price: Optional[float] = None
    unrealized_pnl_quote: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    opened_at: float

    class Config:
        from_attributes = True


class FuturesTradeOut(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    leverage: float
    entry_price: float
    exit_price: float
    qty: float
    pnl_quote: float
    pnl_pct: float
    close_reason: str
    opened_at: float
    closed_at: float

    class Config:
        from_attributes = True


class FuturesLeverageUpdate(BaseModel):
    mode: Optional[str] = None  # "auto" | "manual"
    leverage: Optional[float] = None  # required when setting a manual value
