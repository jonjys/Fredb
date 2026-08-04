"""SQLite-backed state persistence so open positions survive a restart.

All public methods are async wrappers around synchronous SQLAlchemy calls,
executed in a thread pool via asyncio.to_thread — sqlite3 is fast enough for
a scalping bot's write volume and this avoids extra async-driver dependencies.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import time
from typing import List, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, BotState, EquitySnapshot, Position, Trade


class StateStore:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        self.Session: sessionmaker = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init(self, paper_starting_balance: float) -> None:
        Base.metadata.create_all(self.engine)
        with self.Session() as session:
            state = session.get(BotState, 1)
            if state is None:
                today = dt.date.today().isoformat()
                state = BotState(
                    id=1,
                    running=False,
                    kill_switch=False,
                    paper_balance=paper_starting_balance,
                    daily_start_equity=paper_starting_balance,
                    daily_date=today,
                    updated_at=time.time(),
                )
                session.add(state)
                session.commit()

    # ---- BotState -----------------------------------------------------
    def _get_or_create_state(self, session: Session) -> BotState:
        state = session.get(BotState, 1)
        if state is None:
            state = BotState(id=1)
            session.add(state)
            session.commit()
        return state

    def _get_state_sync(self) -> BotState:
        with self.Session() as session:
            return self._get_or_create_state(session)

    async def get_state(self) -> BotState:
        return await asyncio.to_thread(self._get_state_sync)

    def _update_state_sync(self, **kwargs) -> BotState:
        with self.Session() as session:
            state = self._get_or_create_state(session)
            for k, v in kwargs.items():
                setattr(state, k, v)
            state.updated_at = time.time()
            session.commit()
            session.refresh(state)
            return state

    async def update_state(self, **kwargs) -> BotState:
        return await asyncio.to_thread(self._update_state_sync, **kwargs)

    # ---- Positions ------------------------------------------------------
    def _open_position_sync(self, position: Position) -> Position:
        with self.Session() as session:
            session.add(position)
            session.commit()
            session.refresh(position)
            return position

    async def open_position(self, position: Position) -> Position:
        return await asyncio.to_thread(self._open_position_sync, position)

    def _get_open_positions_sync(self, symbol: Optional[str] = None) -> List[Position]:
        with self.Session() as session:
            stmt = select(Position).where(Position.status == "open")
            if symbol:
                stmt = stmt.where(Position.symbol == symbol)
            return list(session.scalars(stmt))

    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        return await asyncio.to_thread(self._get_open_positions_sync, symbol)

    def _update_position_sync(self, position_id: int, **kwargs) -> Optional[Position]:
        with self.Session() as session:
            position = session.get(Position, position_id)
            if position is None:
                return None
            for k, v in kwargs.items():
                setattr(position, k, v)
            session.commit()
            session.refresh(position)
            return position

    async def update_position(self, position_id: int, **kwargs) -> Optional[Position]:
        return await asyncio.to_thread(self._update_position_sync, position_id, **kwargs)

    def _close_position_sync(
        self, position_id: int, exit_price: float, pnl_quote: float, pnl_pct: float, reason: str
    ) -> Optional[Position]:
        with self.Session() as session:
            position = session.get(Position, position_id)
            if position is None:
                return None
            position.status = "closed"
            position.exit_price = exit_price
            position.pnl_quote = pnl_quote
            position.pnl_pct = pnl_pct
            position.close_reason = reason
            position.closed_at = time.time()
            session.commit()
            session.refresh(position)
            return position

    async def close_position(
        self, position_id: int, exit_price: float, pnl_quote: float, pnl_pct: float, reason: str
    ) -> Optional[Position]:
        return await asyncio.to_thread(
            self._close_position_sync, position_id, exit_price, pnl_quote, pnl_pct, reason
        )

    def _get_trade_history_sync(self, limit: int) -> List[Position]:
        with self.Session() as session:
            stmt = (
                select(Position)
                .where(Position.status == "closed")
                .order_by(Position.closed_at.desc())
                .limit(limit)
            )
            return list(session.scalars(stmt))

    async def get_trade_history(self, limit: int = 100) -> List[Position]:
        return await asyncio.to_thread(self._get_trade_history_sync, limit)

    # ---- Trades (individual fills) --------------------------------------
    def _record_trade_sync(self, trade: Trade) -> Trade:
        with self.Session() as session:
            session.add(trade)
            session.commit()
            session.refresh(trade)
            return trade

    async def record_trade(self, trade: Trade) -> Trade:
        return await asyncio.to_thread(self._record_trade_sync, trade)

    # ---- Equity -----------------------------------------------------------
    def _record_equity_sync(self, equity: float, realized_pnl_today: float) -> EquitySnapshot:
        with self.Session() as session:
            snap = EquitySnapshot(equity=equity, realized_pnl_today=realized_pnl_today)
            session.add(snap)
            session.commit()
            session.refresh(snap)
            return snap

    async def record_equity(self, equity: float, realized_pnl_today: float) -> EquitySnapshot:
        return await asyncio.to_thread(self._record_equity_sync, equity, realized_pnl_today)

    def _get_equity_history_sync(self, limit: int) -> List[EquitySnapshot]:
        with self.Session() as session:
            stmt = select(EquitySnapshot).order_by(EquitySnapshot.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt))[::-1]

    async def get_equity_history(self, limit: int = 200) -> List[EquitySnapshot]:
        return await asyncio.to_thread(self._get_equity_history_sync, limit)
