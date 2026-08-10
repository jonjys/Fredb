"""Offline backtesting harness.

Reuses app.strategy.ScalpingStrategy and app.risk.RiskManager directly so a
backtest run exercises the exact same decision code as the live bot, not a
reimplementation of it that could silently drift from production behavior.
"""
