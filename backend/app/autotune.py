# app/autotune.py
"""Nightly walkforward autotune: grid-searches take_profit_pct on the last
autotune_lookback_days of real market data against the strategy that's
actually live (MeanReversionStrategy), and reports whether a different
value would have scored a meaningfully better profit factor.

Suggest-only by default (settings.autotune_auto_apply=False) — see the
settings' docstring in app/config.py for the full reasoning. In short: a
14-day window is a small, noisy sample, and auto-mutating a live bot's risk
parameters from it is a real overfitting/whipsaw risk in its own right, on
top of whatever risk the parameter change itself carries. The dashboard
surfaces the recommendation; a human decides whether to apply it.

Runs inside the same process as the live bots via asyncio.to_thread —
backtest/data.py's downloads are synchronous (requests, not an async HTTP
client), so the grid search must never run directly on the event loop the
live bots' poll ticks depend on, or a nightly run would visibly stall
trading for its duration.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import Settings
from app.risk import RiskManager

logger = logging.getLogger("tradingbot.autotune")


@dataclass
class AutotuneSuggestion:
    ran_at: float
    current_tp: float
    current_pf: Optional[float]
    suggested_tp: Optional[float]
    suggested_pf: Optional[float]
    applied: bool
    note: str
    pf_by_candidate: Dict[float, Optional[float]] = field(default_factory=dict)


class Autotuner:
    """Owns the nightly schedule and the last result. One instance is
    shared between the spot and futures bots (both read the same
    settings.take_profit_pct) via main.py's lifespan.
    """

    def __init__(self, settings: Settings, symbols: List[str]):
        self.settings = settings
        self.symbols = symbols
        self.last_result: Optional[AutotuneSuggestion] = None
        self._task: Optional[asyncio.Task] = None
        self._stopping = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()

    async def run_now(self) -> AutotuneSuggestion:
        """Manual trigger (e.g. a dashboard "run now" button) — bypasses
        the schedule but goes through the same to_thread path."""
        result = await asyncio.to_thread(self._grid_search_sync)
        self.last_result = result
        return result

    async def _run_loop(self) -> None:
        while not self._stopping:
            await self._sleep_until_next_run()
            if self._stopping:
                return
            if not self.settings.autotune_enabled:
                continue
            try:
                await self.run_now()
                self._log_result(self.last_result)
            except Exception:
                logger.exception("Autotune run failed — will retry at the next scheduled run")
            # Guards against firing twice if a run finishes in under a
            # minute and the next loop iteration re-evaluates the same clock minute.
            await asyncio.sleep(60)

    async def _sleep_until_next_run(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        target = now.replace(hour=self.settings.autotune_hour_utc, minute=0, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())

    def _log_result(self, result: AutotuneSuggestion) -> None:
        if result.suggested_tp is not None:
            logger.warning(
                "Autotune suggestion: take_profit_pct %.2f%% -> %.2f%% (PF %s -> %.2f)%s",
                result.current_tp, result.suggested_tp,
                f"{result.current_pf:.2f}" if result.current_pf is not None else "n/a",
                result.suggested_pf,
                " [APPLIED]" if result.applied else " [not applied — set autotune_auto_apply=true to enable]",
            )
        else:
            logger.info(
                "Autotune: take_profit_pct=%.2f%% already best of the tested candidates (%s)",
                result.current_tp, result.note,
            )

    # ---- The actual grid search, run off the event loop --------------------
    def _grid_search_sync(self) -> AutotuneSuggestion:
        from app.mean_reversion import MeanReversionStrategy, attach_htf_bias
        from backtest.data import load_klines
        from backtest.engine import BacktestEngine
        from backtest.report import build_report

        end = dt.date.today() - dt.timedelta(days=2)  # daily archives lag by ~1-2 days
        start = end - dt.timedelta(days=self.settings.autotune_lookback_days)

        try:
            data = {}
            for symbol in self.symbols:
                df_1m = load_klines(symbol, start, end, timeframe="1m")
                df_htf = load_klines(symbol, start, end, timeframe=self.settings.htf_timeframe)
                data[symbol] = attach_htf_bias(df_1m, df_htf, ema_period=self.settings.htf_ema_period)
        except Exception:
            logger.exception("Autotune: failed to load historical data — skipping tonight's run")
            return AutotuneSuggestion(
                ran_at=time.time(), current_tp=self.settings.take_profit_pct, current_pf=None,
                suggested_tp=None, suggested_pf=None, applied=False, note="historical data load failed",
            )

        def make_strategy() -> MeanReversionStrategy:
            return MeanReversionStrategy(
                bb_period=self.settings.mr_bb_period, bb_std=self.settings.mr_bb_std,
                rsi_period=self.settings.mr_rsi_period, rsi_oversold=self.settings.mr_rsi_oversold,
                rsi_overbought=self.settings.mr_rsi_overbought,
                volume_sma_period=self.settings.mr_volume_sma_period,
                min_distance_std=self.settings.mr_min_distance_std,
            )

        pf_by_candidate: Dict[float, Optional[float]] = {}
        for tp in self.settings.autotune_tp_candidates:
            candidate_settings = self.settings.model_copy(update={"take_profit_pct": tp})
            # Never test (or suggest) a TP the bot would refuse to start
            # with — see RiskManager.is_take_profit_worth_it.
            if not RiskManager(candidate_settings).is_take_profit_worth_it():
                logger.warning(
                    "Autotune: skipping TP candidate %.2f%% — fails is_take_profit_worth_it()", tp
                )
                continue
            engine = BacktestEngine(
                candidate_settings, data, leverage_mode="auto", strategy=make_strategy()
            )
            report = build_report(engine.run())
            pf_by_candidate[tp] = report.stats.profit_factor

        current_pf = pf_by_candidate.get(self.settings.take_profit_pct)
        result = AutotuneSuggestion(
            ran_at=time.time(), current_tp=self.settings.take_profit_pct, current_pf=current_pf,
            suggested_tp=None, suggested_pf=None, applied=False, note="", pf_by_candidate=pf_by_candidate,
        )
        if not pf_by_candidate:
            result.note = "no candidate produced a valid profit factor"
            return result

        scored = {tp: pf for tp, pf in pf_by_candidate.items() if pf is not None}
        if not scored:
            result.note = "no candidate had any losing trades to compute a profit factor from"
            return result

        best_tp = max(scored, key=lambda tp: scored[tp])
        best_pf = scored[best_tp]
        result.note = f"PF by TP candidate: {pf_by_candidate}"

        worth_suggesting = best_tp != self.settings.take_profit_pct and (
            current_pf is None or current_pf <= 0
            or best_pf >= current_pf * self.settings.autotune_min_pf_improvement_multiple
        )
        if not worth_suggesting:
            return result

        result.suggested_tp = best_tp
        result.suggested_pf = best_pf
        if self.settings.autotune_auto_apply:
            # In-process mutation of the shared Settings singleton — both
            # bot.py and futures_bot.py hold a reference to the same
            # object (see main.py), so this takes effect on their very
            # next tick without a restart.
            self.settings.take_profit_pct = best_tp
            result.applied = True
        return result
