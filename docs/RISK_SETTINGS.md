# Recommended Risk Settings

These are starting points for small live balances, tuned conservatively.
Adjust from the dashboard's Settings panel (or via env vars) once you have
real data on how the strategy performs for your symbols.

| Parameter | Recommended start | Env var | Notes |
|---|---|---|---|
| Max risk per trade | **1%** | `MAX_RISK_PER_TRADE_PCT=1.0` | Fraction of equity lost if a position hits its stop-loss. Never exceed 2% while live-testing. |
| Max concurrent positions | **3** | `MAX_CONCURRENT_POSITIONS=3` | Caps total exposure; also divides equity into per-position allocation caps. |
| Take profit | **0.6%** | `TAKE_PROFIT_PCT=0.6` | Must exceed round-trip cost (2× fee + 2× slippage buffer) or every win is a loss after costs — the bot logs a warning-worthy config via `RiskManager.is_take_profit_worth_it()`. |
| Trailing stop | **0.3%** | `TRAILING_STOP_PCT=0.3` | Activates only after take-profit is first reached; locks in gains while letting strong moves run. |
| Stop loss floor | **0.4%** | `STOP_LOSS_PCT=0.4` | Hard floor on stop distance — actual distance is `max(ATR% × multiplier, this, 0.15%)`, so this only binds in very low-volatility conditions. |
| ATR multiplier | **1.5** | `ATR_MULTIPLIER=1.5` | Higher = wider stops in volatile markets, fewer noise stop-outs, larger per-trade loss if wrong. |
| Max daily loss (kill switch) | **5%** | `MAX_DAILY_LOSS_PCT=5.0` | Once equity drawdown from the day's starting value hits this, the bot force-closes all positions and halts new entries until the next UTC day. |
| Taker fee assumption | **0.1%** | `TAKER_FEE_PCT=0.1` | Binance default spot taker fee (before any BNB discount). Set to your actual tier. |
| Slippage buffer | **0.05%** | `SLIPPAGE_BUFFER_PCT=0.05` | Used by the paper broker to simulate realistic fills, and by the round-trip-cost sanity check. |
| Poll interval | **5s** | `POLL_INTERVAL_SECONDS=5` | How often the loop re-evaluates. Lower = more responsive/scalpy, more API calls (watch exchange rate limits). |

## Why these numbers

- **1% risk/trade × 3 concurrent positions** means a worst case of all
  three stopping out simultaneously costs ~3% of equity — survivable, not
  catastrophic, and still leaves room before the 5% daily kill-switch.
- **Take-profit > round-trip cost** is a hard requirement, not a
  suggestion. At 0.1% fee and 0.05% slippage buffer, round-trip cost is
  `2×0.1 + 2×0.05 = 0.3%`. A 0.6% take-profit clears that with margin;
  going lower (e.g. 0.2%) means winning trades can still net negative
  after fees.
- **5% daily kill-switch** stops a bad day from becoming a bad month. It
  resets at UTC midnight (see `TradingBot._roll_daily_window_if_needed` in
  [backend/app/bot.py](../backend/app/bot.py)).

## Position sizing formula

See [backend/app/risk.py](../backend/app/risk.py) `RiskManager.size_position`:

```
stop_distance_pct = max(ATR% × atr_multiplier, stop_loss_pct, 0.15%)
risk_amount        = equity × max_risk_per_trade_pct
qty_by_risk         = risk_amount / (entry_price × stop_distance_pct)
qty_by_allocation   = (equity / max_concurrent_positions) / entry_price
qty                 = min(qty_by_risk, qty_by_allocation)
```

Volatility-adjusted: in choppy, high-ATR markets the stop is wider, so
position size shrinks automatically to keep dollar risk constant.

## Scaling up

Only increase risk parameters after you have:
1. Multiple consecutive weeks of testnet operation with no unexplained
   behavior (missed kill-switch triggers, stuck positions, crashed loops).
2. At least a few weeks of live operation at the conservative settings
   above, with a real (small) balance, showing the strategy's actual edge
   (or lack thereof) net of real fees and slippage.

Scale the **balance** before you scale the **risk percentage** — a bigger
account at 1% risk/trade is safer than a small account at 5% risk/trade.
