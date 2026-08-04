"""SQLAlchemy ORM models for state persistence (positions survive restarts)."""
from __future__ import annotations

import time

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String, default="long")
    status: Mapped[str] = mapped_column(String, default="open", index=True)  # open|closed

    entry_price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)

    stop_loss_price: Mapped[float] = mapped_column(Float)
    take_profit_price: Mapped[float] = mapped_column(Float)
    trailing_active: Mapped[bool] = mapped_column(Boolean, default=False)
    trailing_high: Mapped[float] = mapped_column(Float, default=0.0)

    exit_price: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_quote: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)

    opened_at: Mapped[float] = mapped_column(Float, default=time.time)
    closed_at: Mapped[float] = mapped_column(Float, default=0.0)
    close_reason: Mapped[str] = mapped_column(String, default="")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)  # buy|sell
    trade_type: Mapped[str] = mapped_column(String)  # entry|exit
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    fee_quote: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time)
    equity: Mapped[float] = mapped_column(Float)
    realized_pnl_today: Mapped[float] = mapped_column(Float, default=0.0)


class BotState(Base):
    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    kill_switch_reason: Mapped[str] = mapped_column(String, default="")
    paper_balance: Mapped[float] = mapped_column(Float, default=1000.0)
    daily_start_equity: Mapped[float] = mapped_column(Float, default=1000.0)
    daily_date: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
