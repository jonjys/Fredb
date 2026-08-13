# app/main.py
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

from app.autotune import Autotuner
from app.bot import TradingBot
from app.config import settings
from dataclasses import asdict

from app.futures_bot import FuturesTradingBot, _directional_pnl
from app.stats import compute_stats
from app.logger import log_buffer, setup_logging
from app.models import FuturesBotState, FuturesEquitySnapshot, FuturesPosition, FuturesTrade
from app.schemas import (
    AutotuneStatusOut,
    CandlePoint,
    EquityPointOut,
    FuturesLeverageUpdate,
    FuturesPositionOut,
    FuturesStatusResponse,
    FuturesTradeOut,
    LogEntryOut,
    OhlcvBarOut,
    OrderBookOut,
    PerformanceStatsOut,
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

futures_store = StateStore(
    settings.database_path, FuturesPosition, FuturesTrade, FuturesBotState, FuturesEquitySnapshot
)
futures_bot = FuturesTradingBot(settings, futures_store)

# Autotune needs futures-shaped settings (leverage, margin) that BacktestEngine
# assumes — gated on futures_enabled rather than run against the spot bot's
# economics, which the engine was never built to model.
autotuner = Autotuner(settings, settings.futures_symbols) if settings.futures_enabled else None

bearer_scheme = HTTPBearer(auto_error=False)


def require_auth(creds: HTTPAuthorizationCredentials = Security(bearer_scheme)) -> None:
    if creds is None or creds.credentials != settings.dashboard_api_token:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.start_background_loop()
    if settings.futures_enabled:
        await futures_bot.start_background_loop()
        if autotuner and settings.autotune_enabled:
            autotuner.start()
    yield
    await bot.shutdown()
    if settings.futures_enabled:
        await futures_bot.shutdown()
        if autotuner:
            autotuner.stop()


def require_futures_enabled() -> None:
    if not settings.futures_enabled:
        raise HTTPException(status_code=503, detail="Futures trading is not enabled on this backend")


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
        throttle_paused_until=state.throttle_paused_until,
        consecutive_losses=state.consecutive_losses,
        reduced_size_trades_remaining=state.reduced_size_trades_remaining,
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


@app.get("/api/stats", response_model=PerformanceStatsOut, dependencies=[Depends(require_auth)])
async def get_stats(limit: int = 500):
    history = await store.get_trade_history(limit)
    return PerformanceStatsOut(**asdict(compute_stats(history)))


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


@app.post("/api/bot/reset", dependencies=[Depends(require_auth)])
async def reset_bot():
    """Hard reset: wipe every position/trade/equity point and restart the
    paper wallet at the configured starting balance, as if the bot had
    never run. Paper mode only — refuses on testnet/live, where "reset"
    would mean discarding a record of real orders, not just paper history.
    """
    if settings.bot_mode != "paper":
        raise HTTPException(status_code=409, detail="Reset is only available in paper mode")
    await store.reset_paper_account(settings.paper_starting_balance)
    bot.broker.quote_balance = settings.paper_starting_balance  # type: ignore[attr-defined]
    bot.broker.base_holdings = {}  # type: ignore[attr-defined]
    bot._last_prices.clear()
    logger.info("Spot paper account reset to $%.2f by dashboard", settings.paper_starting_balance)
    return {"reset": True, "paper_balance": settings.paper_starting_balance}


@app.get(
    "/api/positions/{position_id}/candles",
    response_model=List[CandlePoint],
    dependencies=[Depends(require_auth)],
)
async def get_position_candles(position_id: int, limit: int = 60):
    positions = await store.get_open_positions()
    position = next((p for p in positions if p.id == position_id), None)
    if position is None:
        raise HTTPException(status_code=404, detail="Open position not found")
    df = await bot.broker.get_ohlcv(position.symbol, settings.timeframe, limit=limit)
    return [CandlePoint(timestamp=float(row.timestamp) / 1000, close=float(row.close)) for row in df.itertuples()]


@app.get("/api/market/ohlcv", response_model=List[OhlcvBarOut], dependencies=[Depends(require_auth)])
async def get_market_ohlcv(symbol: str, timeframe: str = "1m", limit: int = 100):
    """Full OHLCV bars for a symbol's-eye chart — unlike the per-position
    candles endpoint above (which only needs close for a sparkline), this
    keeps high/low/open so the frontend can render a real candlestick."""
    df = await bot.broker.get_ohlcv(symbol, timeframe, limit=limit)
    return [
        OhlcvBarOut(
            timestamp=float(row.timestamp) / 1000, open=float(row.open), high=float(row.high),
            low=float(row.low), close=float(row.close), volume=float(row.volume),
        )
        for row in df.itertuples()
    ]


@app.get("/api/market/orderbook", response_model=OrderBookOut, dependencies=[Depends(require_auth)])
async def get_market_orderbook(symbol: str, limit: int = 15):
    book = await bot.broker.get_order_book(symbol, limit)
    return OrderBookOut(symbol=symbol, bids=book["bids"], asks=book["asks"])


# ============================================================================
# Futures (leveraged) — all routes 503 if FUTURES_ENABLED is not set.
# ============================================================================


@app.get(
    "/api/futures/status",
    response_model=FuturesStatusResponse,
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_status():
    state = await futures_store.get_state()
    equity = await futures_bot._compute_equity()
    open_positions = await futures_store.get_open_positions()
    daily_pnl = equity - state.daily_start_equity
    daily_pnl_pct = (daily_pnl / state.daily_start_equity * 100) if state.daily_start_equity else 0.0
    active_symbols = await futures_bot._get_active_symbols()
    return FuturesStatusResponse(
        enabled=True,
        mode=settings.futures_mode,
        exchange=settings.futures_exchange_id,
        symbols=active_symbols,
        running=state.running,
        kill_switch=state.kill_switch,
        kill_switch_reason=state.kill_switch_reason,
        equity=equity,
        quote_balance=await futures_bot.broker.get_quote_balance(),
        daily_start_equity=state.daily_start_equity,
        daily_pnl=daily_pnl,
        daily_pnl_pct=daily_pnl_pct,
        open_positions_count=len(open_positions),
        max_concurrent_positions=settings.max_concurrent_positions,
        leverage_default=state.leverage,
        leverage_mode=state.leverage_mode,
        max_leverage=settings.futures_max_leverage,
        auto_leverage_min=settings.futures_auto_leverage_min,
        auto_leverage_max=settings.futures_auto_leverage_max,
        throttle_paused_until=state.throttle_paused_until,
        consecutive_losses=state.consecutive_losses,
        reduced_size_trades_remaining=state.reduced_size_trades_remaining,
    )


@app.get(
    "/api/futures/positions",
    response_model=List[FuturesPositionOut],
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_positions():
    positions = await futures_store.get_open_positions()
    out = []
    for p in positions:
        current_price = futures_bot._last_prices.get(p.symbol)
        unrealized_quote = None
        unrealized_pct = None
        if current_price:
            unrealized_quote = _directional_pnl(p.side, p.entry_price, current_price, p.qty)
            unrealized_pct = (unrealized_quote / p.margin_used * 100) if p.margin_used else None
        out.append(
            FuturesPositionOut(
                id=p.id,
                symbol=p.symbol,
                side=p.side,
                status=p.status,
                leverage=p.leverage,
                entry_price=p.entry_price,
                qty=p.qty,
                margin_used=p.margin_used,
                liquidation_price=p.liquidation_price,
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


@app.get(
    "/api/futures/trades",
    response_model=List[FuturesTradeOut],
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_trades(limit: int = 100):
    history = await futures_store.get_trade_history(limit)
    return [
        FuturesTradeOut(
            id=p.id,
            symbol=p.symbol,
            side=p.side,
            status=p.status,
            leverage=p.leverage,
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


@app.get(
    "/api/futures/stats",
    response_model=PerformanceStatsOut,
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_stats(limit: int = 500):
    history = await futures_store.get_trade_history(limit)
    return PerformanceStatsOut(**asdict(compute_stats(history)))


@app.get(
    "/api/futures/equity_history",
    response_model=List[EquityPointOut],
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_equity_history(limit: int = 200):
    history = await futures_store.get_equity_history(limit)
    return [
        EquityPointOut(timestamp=s.timestamp, equity=s.equity, realized_pnl_today=s.realized_pnl_today)
        for s in history
    ]


@app.get(
    "/api/futures/logs",
    response_model=List[LogEntryOut],
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_logs(limit: int = 200):
    entries = log_buffer.recent(limit, logger_prefix="tradingbot.futures_bot")
    return [LogEntryOut(timestamp=e.timestamp, level=e.level, message=e.message) for e in entries]


@app.put(
    "/api/futures/leverage",
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def set_futures_leverage(update: FuturesLeverageUpdate):
    if update.mode == "auto":
        await futures_bot.set_leverage_mode("auto")
        return {"leverage_mode": "auto"}

    if update.leverage is None:
        raise HTTPException(status_code=400, detail="leverage is required when not switching to auto")
    if update.leverage < 1 or update.leverage > settings.futures_max_leverage:
        raise HTTPException(
            status_code=400,
            detail=f"Leverage must be between 1x and {settings.futures_max_leverage}x",
        )
    await futures_bot.set_leverage_default(update.leverage)
    return {"leverage": update.leverage, "leverage_mode": "manual"}


@app.post(
    "/api/futures/bot/start", dependencies=[Depends(require_auth), Depends(require_futures_enabled)]
)
async def start_futures_bot():
    state = await futures_store.get_state()
    if state.kill_switch:
        raise HTTPException(
            status_code=409, detail="Kill switch is active — reset it before starting the bot"
        )
    await futures_bot.set_running(True)
    return {"running": True}


@app.post(
    "/api/futures/bot/stop", dependencies=[Depends(require_auth), Depends(require_futures_enabled)]
)
async def stop_futures_bot():
    await futures_bot.set_running(False)
    return {"running": False}


@app.post(
    "/api/futures/bot/kill", dependencies=[Depends(require_auth), Depends(require_futures_enabled)]
)
async def kill_futures_bot():
    await futures_bot.emergency_kill("manual kill switch from dashboard")
    return {"kill_switch": True}


@app.post(
    "/api/futures/bot/kill/reset",
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def reset_futures_kill():
    await futures_bot.reset_kill_switch()
    return {"kill_switch": False}


@app.post(
    "/api/futures/bot/reset",
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def reset_futures_bot():
    if settings.futures_mode != "paper":
        raise HTTPException(status_code=409, detail="Reset is only available in paper mode")
    await futures_store.reset_paper_account(settings.futures_paper_starting_balance)
    futures_bot.broker.quote_balance = settings.futures_paper_starting_balance  # type: ignore[attr-defined]
    futures_bot._last_prices.clear()
    futures_bot._leverage_refreshed_at = 0.0
    logger.info(
        "Futures paper account reset to $%.2f by dashboard", settings.futures_paper_starting_balance
    )
    return {"reset": True, "paper_balance": settings.futures_paper_starting_balance}


@app.get(
    "/api/futures/positions/{position_id}/candles",
    response_model=List[CandlePoint],
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_position_candles(position_id: int, limit: int = 60):
    positions = await futures_store.get_open_positions()
    position = next((p for p in positions if p.id == position_id), None)
    if position is None:
        raise HTTPException(status_code=404, detail="Open position not found")
    df = await futures_bot.broker.get_ohlcv(position.symbol, settings.timeframe, limit=limit)
    return [CandlePoint(timestamp=float(row.timestamp) / 1000, close=float(row.close)) for row in df.itertuples()]


@app.get(
    "/api/futures/market/ohlcv",
    response_model=List[OhlcvBarOut],
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_market_ohlcv(symbol: str, timeframe: str = "1m", limit: int = 100):
    df = await futures_bot.broker.get_ohlcv(symbol, timeframe, limit=limit)
    return [
        OhlcvBarOut(
            timestamp=float(row.timestamp) / 1000, open=float(row.open), high=float(row.high),
            low=float(row.low), close=float(row.close), volume=float(row.volume),
        )
        for row in df.itertuples()
    ]


@app.get(
    "/api/futures/market/orderbook",
    response_model=OrderBookOut,
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_futures_market_orderbook(symbol: str, limit: int = 15):
    book = await futures_bot.broker.get_order_book(symbol, limit)
    return OrderBookOut(symbol=symbol, bids=book["bids"], asks=book["asks"])


def _autotune_status_response() -> AutotuneStatusOut:
    base = dict(
        enabled=settings.autotune_enabled,
        auto_apply=settings.autotune_auto_apply,
        hour_utc=settings.autotune_hour_utc,
        lookback_days=settings.autotune_lookback_days,
        current_tp=settings.take_profit_pct,
    )
    if autotuner is None or autotuner.last_result is None:
        return AutotuneStatusOut(**base)
    result = autotuner.last_result
    return AutotuneStatusOut(
        **{**base, "current_tp": result.current_tp},
        ran_at=result.ran_at,
        current_pf=result.current_pf,
        suggested_tp=result.suggested_tp,
        suggested_pf=result.suggested_pf,
        applied=result.applied,
        note=result.note,
    )


@app.get(
    "/api/autotune/status",
    response_model=AutotuneStatusOut,
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def get_autotune_status():
    return _autotune_status_response()


@app.post(
    "/api/autotune/run",
    response_model=AutotuneStatusOut,
    dependencies=[Depends(require_auth), Depends(require_futures_enabled)],
)
async def run_autotune_now():
    """Manual trigger — same grid search the nightly schedule runs, useful
    to preview a suggestion without waiting for autotune_hour_utc."""
    if autotuner is None:
        raise HTTPException(status_code=503, detail="Autotune is not available on this backend")
    await autotuner.run_now()
    return _autotune_status_response()
