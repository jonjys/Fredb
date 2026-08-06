"""SQLite-backed state persistence so open positions survive a restart.

All public methods are async wrappers around synchronous SQLAlchemy calls,
executed in a thread pool via asyncio.to_thread — sqlite3 is fast enough for
a scalping bot's write volume and this avoids extra async-driver dependencies.

Parameterized by model class (Position/Trade/BotState/EquitySnapshot) so the
same store implementation backs both the spot tables and the isolated
futures tables — two instances, two independent sets of tables, same code.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import time
from typing import List, Optional, Type

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, BotState, EquitySnapshot, Position, Trade

logger = logging.getLogger("tradingbot.state_store")


class StateStore:
    def __init__(
        self,
        db_path: str,
        position_cls: Type = Position,
        trade_cls: Type = Trade,
        bot_state_cls: Type = BotState,
        equity_cls: Type = EquitySnapshot,
    ):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        self.Session: sessionmaker = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.Position = position_cls
        self.Trade = trade_cls
        self.BotState = bot_state_cls
        self.EquitySnapshot = equity_cls

    def _ensure_schema(self) -> None:
        """Add any model columns missing from the actual SQLite tables.

        Base.metadata.create_all() only creates tables that don't exist yet
        — it never alters an existing table when the model gains a new
        column, which is exactly what happens when this app evolves after
        its first deploy (e.g. FuturesBotState.leverage_mode added after
        futures_bot_state already existed on a live volume). This is a
        deliberately small stand-in for a real migration tool: additive
        (ADD COLUMN) only, safe to run on every startup, no-op when the
        schema already matches.
        """
        with self.engine.connect() as conn:
            for model in (self.Position, self.Trade, self.BotState, self.EquitySnapshot):
                table_name = model.__tablename__
                existing_columns = {
                    row[1]  # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
                    for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
                }
                if not existing_columns:
                    continue  # table doesn't exist yet — create_all() already handled it fully
                for column in model.__table__.columns:
                    if column.name in existing_columns:
                        continue
                    ddl = self._sqlite_add_column_ddl(column)
                    conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")
                    logger.warning("Migrated %s: added missing column %s", table_name, column.name)
            conn.commit()

    @staticmethod
    def _sqlite_add_column_ddl(column) -> str:
        py_type = column.type.python_type
        if py_type is bool:
            sqlite_type, default = "BOOLEAN", column.default.arg if column.default else False
            default_sql = "1" if default else "0"
        elif py_type is int:
            sqlite_type, default = "INTEGER", column.default.arg if column.default else 0
            default_sql = str(default) if not callable(default) else "0"
        elif py_type is float:
            sqlite_type, default = "REAL", column.default.arg if column.default else 0.0
            default_sql = str(default) if not callable(default) else "0.0"
        else:
            sqlite_type = "TEXT"
            default = column.default.arg if column.default else ""
            default = "" if callable(default) else default
            default_sql = "'{}'".format(str(default).replace("'", "''"))
        return f"{column.name} {sqlite_type} DEFAULT {default_sql}"

    def init(self, paper_starting_balance: float) -> None:
        Base.metadata.create_all(self.engine)
        self._ensure_schema()
        with self.Session() as session:
            state = session.get(self.BotState, 1)
            if state is None:
                today = dt.date.today().isoformat()
                state = self.BotState(
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
    def _get_or_create_state(self, session: Session):
        state = session.get(self.BotState, 1)
        if state is None:
            state = self.BotState(id=1)
            session.add(state)
            session.commit()
        return state

    def _get_state_sync(self):
        with self.Session() as session:
            return self._get_or_create_state(session)

    async def get_state(self):
        return await asyncio.to_thread(self._get_state_sync)

    def _update_state_sync(self, **kwargs):
        with self.Session() as session:
            state = self._get_or_create_state(session)
            for k, v in kwargs.items():
                setattr(state, k, v)
            state.updated_at = time.time()
            session.commit()
            session.refresh(state)
            return state

    async def update_state(self, **kwargs):
        return await asyncio.to_thread(self._update_state_sync, **kwargs)

    # ---- Positions ------------------------------------------------------
    def _open_position_sync(self, position):
        with self.Session() as session:
            session.add(position)
            session.commit()
            session.refresh(position)
            return position

    async def open_position(self, position):
        return await asyncio.to_thread(self._open_position_sync, position)

    def _get_open_positions_sync(self, symbol: Optional[str] = None) -> List:
        with self.Session() as session:
            stmt = select(self.Position).where(self.Position.status == "open")
            if symbol:
                stmt = stmt.where(self.Position.symbol == symbol)
            return list(session.scalars(stmt))

    async def get_open_positions(self, symbol: Optional[str] = None) -> List:
        return await asyncio.to_thread(self._get_open_positions_sync, symbol)

    def _update_position_sync(self, position_id: int, **kwargs):
        with self.Session() as session:
            position = session.get(self.Position, position_id)
            if position is None:
                return None
            for k, v in kwargs.items():
                setattr(position, k, v)
            session.commit()
            session.refresh(position)
            return position

    async def update_position(self, position_id: int, **kwargs):
        return await asyncio.to_thread(self._update_position_sync, position_id, **kwargs)

    def _close_position_sync(
        self, position_id: int, exit_price: float, pnl_quote: float, pnl_pct: float, reason: str
    ):
        with self.Session() as session:
            position = session.get(self.Position, position_id)
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
    ):
        return await asyncio.to_thread(
            self._close_position_sync, position_id, exit_price, pnl_quote, pnl_pct, reason
        )

    def _get_trade_history_sync(self, limit: int) -> List:
        with self.Session() as session:
            stmt = (
                select(self.Position)
                .where(self.Position.status == "closed")
                .order_by(self.Position.closed_at.desc())
                .limit(limit)
            )
            return list(session.scalars(stmt))

    async def get_trade_history(self, limit: int = 100) -> List:
        return await asyncio.to_thread(self._get_trade_history_sync, limit)

    # ---- Trades (individual fills) --------------------------------------
    def _record_trade_sync(self, trade):
        with self.Session() as session:
            session.add(trade)
            session.commit()
            session.refresh(trade)
            return trade

    async def record_trade(self, trade):
        return await asyncio.to_thread(self._record_trade_sync, trade)

    # ---- Equity -----------------------------------------------------------
    def _record_equity_sync(self, equity: float, realized_pnl_today: float):
        with self.Session() as session:
            snap = self.EquitySnapshot(equity=equity, realized_pnl_today=realized_pnl_today)
            session.add(snap)
            session.commit()
            session.refresh(snap)
            return snap

    async def record_equity(self, equity: float, realized_pnl_today: float):
        return await asyncio.to_thread(self._record_equity_sync, equity, realized_pnl_today)

    def _get_equity_history_sync(self, limit: int) -> List:
        with self.Session() as session:
            stmt = (
                select(self.EquitySnapshot).order_by(self.EquitySnapshot.timestamp.desc()).limit(limit)
            )
            return list(session.scalars(stmt))[::-1]

    async def get_equity_history(self, limit: int = 200) -> List:
        return await asyncio.to_thread(self._get_equity_history_sync, limit)
