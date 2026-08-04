"""FastAPI application: REST API consumed by the Next.js dashboard.

Security: every /api/* route (except /api/health) requires a Bearer token
matching DASHBOARD_API_TOKEN. The frontend never talks to this API directly
from the browser with a hardcoded key — it proxies through Next.js server
routes that attach the token server-side (see frontend/app/lib/api.ts).
"""
from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.bot import TradingBot
from app.config import settings
from app.logger import log_buffer, setup_logging
from app.schemas import (
    EquityPointOut,
    LogEntryOut,
    PositionOut,
    SettingsOut,
    SettingsUpdate,
    StatusResponse,
    TradeOut,
)
from app.state_store import StateStore

logger = setup_logging(settings.log_level)
store = StateStore(settings.database_path)
bot = TradingBot(settings, store)

bearer_scheme = HTTPBearer(auto_error=False)


def require_auth(creds: HTTPAuthorizationCredentials = Security(bearer_scheme)) -> None:
    if creds is None or creds.credentials != settings.dashboard_api_token:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.start_background_loop()
    yield
    await bot.shutdown()


app = FastAPI(title="Trading Bot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status", response_model=StatusResponse, dependencies=[Depends(require_auth)])
async def get_status():
    state = await store.get_state()
    equity = await bot._compute_equity()
    open_positions = await store.get_open_positions()
    daily_pnl = equity - state.daily_start_equity
    daily_pnl_pct = (daily_pnl / state.daily_start_equity * 100) if state.daily_start_equity else 0.0
    return StatusResponse(
        mode=settings.bot_mode,
        exchange=settings.exchange_id,
        symbols=settings.symbols,
        running=state.running,
        kill_switch=state.kill_switch,
        kill_switch_reason=state.kill_switch_reason,
        equity=equity,
        quote_balance=await bot.broker.get_quote_balance(),
        daily_start_equity=state.daily_start_equity,
        daily_pnl=daily_pnl,
        daily_pnl_pct=daily_pnl_pct,
        open_positions_count=len(open_positions),
        max_concurrent_positions=settings.max_concurrent_positions,
    )


@app.get("/api/positions", response_model=List[PositionOut], dependencies=[Depends(require_auth)])
async def get_positions():
    positions = await store.get_open_positions()
    out = []
    for p in positions:
        current_price = bot._last_prices.get(p.symbol)
        unrealized_quote = None
        unrealized_pct = None
        if current_price:
            unrealized_quote = (current_price - p.entry_price) * p.qty
            unrealized_pct = (current_price - p.entry_price) / p.entry_price * 100
        out.append(
            PositionOut(
                id=p.id,
                symbol=p.symbol,
                side=p.side,
                status=p.status,
                entry_price=p.entry_price,
                qty=p.qty,
                stop_loss_price=p.stop_loss_price,
                take_profit_price=p.take_profit_price,
                trailing_active=p.trailing_active,
                trailing_high=p.trailing_high,
                current_price=current_price,
                unrealized_pnl_quote=unrealized_quote,
                unrealized_pnl_pct=unrealized_pct,
                opened_at=p.opened_at,
            )
        )
    return out


@app.get("/api/trades", response_model=List[TradeOut], dependencies=[Depends(require_auth)])
async def get_trades(limit: int = 100):
    history = await store.get_trade_history(limit)
    return [
        TradeOut(
            id=p.id,
            symbol=p.symbol,
            side=p.side,
            status=p.status,
            entry_price=p.entry_price,
            exit_price=p.exit_price,
            qty=p.qty,
            pnl_quote=p.pnl_quote,
            pnl_pct=p.pnl_pct,
            close_reason=p.close_reason,
            opened_at=p.opened_at,
            closed_at=p.closed_at,
        )
        for p in history
    ]


@app.get("/api/equity_history", response_model=List[EquityPointOut], dependencies=[Depends(require_auth)])
async def get_equity_history(limit: int = 200):
    history = await store.get_equity_history(limit)
    return [
        EquityPointOut(timestamp=s.timestamp, equity=s.equity, realized_pnl_today=s.realized_pnl_today)
        for s in history
    ]


@app.get("/api/logs", response_model=List[LogEntryOut], dependencies=[Depends(require_auth)])
async def get_logs(limit: int = 200):
    entries = log_buffer.recent(limit)
    return [LogEntryOut(timestamp=e.timestamp, level=e.level, message=e.message) for e in entries]


@app.get("/api/settings", response_model=SettingsOut, dependencies=[Depends(require_auth)])
async def get_settings():
    return SettingsOut(
        max_risk_per_trade_pct=settings.max_risk_per_trade_pct,
        max_concurrent_positions=settings.max_concurrent_positions,
        take_profit_pct=settings.take_profit_pct,
        trailing_stop_pct=settings.trailing_stop_pct,
        stop_loss_pct=settings.stop_loss_pct,
        atr_multiplier=settings.atr_multiplier,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        taker_fee_pct=settings.taker_fee_pct,
        slippage_buffer_pct=settings.slippage_buffer_pct,
        poll_interval_seconds=settings.poll_interval_seconds,
    )


@app.put("/api/settings", response_model=SettingsOut, dependencies=[Depends(require_auth)])
async def update_settings(update: SettingsUpdate):
    data = update.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(settings, key, value)
    logger.info("Risk settings updated via dashboard: %s", data)
    return await get_settings()


@app.post("/api/bot/start", dependencies=[Depends(require_auth)])
async def start_bot():
    state = await store.get_state()
    if state.kill_switch:
        raise HTTPException(
            status_code=409, detail="Kill switch is active — reset it before starting the bot"
        )
    await bot.set_running(True)
    return {"running": True}


@app.post("/api/bot/stop", dependencies=[Depends(require_auth)])
async def stop_bot():
    await bot.set_running(False)
    return {"running": False}


@app.post("/api/bot/kill", dependencies=[Depends(require_auth)])
async def kill_bot():
    await bot.emergency_kill("manual kill switch from dashboard")
    return {"kill_switch": True}


@app.post("/api/bot/kill/reset", dependencies=[Depends(require_auth)])
async def reset_kill():
    await bot.reset_kill_switch()
    return {"kill_switch": False}
