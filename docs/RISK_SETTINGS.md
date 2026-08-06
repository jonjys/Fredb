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

## Futures (leveraged) trading

Enabled via `FUTURES_ENABLED=true`, runs as a second, independent bot
against Binance USDT-M perpetual futures (`backend/app/futures_bot.py`).
Off by default — this is materially higher risk than spot and should not
be turned on casually.

**The one thing to understand:** leverage does not, by itself, change how
much you risk per trade. `RiskManager.size_position_leveraged` uses the
exact same dollar-risk formula as spot (`equity × MAX_RISK_PER_TRADE_PCT`),
then simply divides the resulting notional by leverage to get the margin
requirement. Higher leverage means less margin locked per position (more
capital free for other positions), **not** a bigger loss on a losing trade
— as long as the stop-loss actually fires.

**Where the real risk is:** liquidation. At leverage `L`, a roughly `1/L`
adverse price move liquidates the position outright, regardless of where
your stop-loss is set — Binance's liquidation engine doesn't know or care
about our stop order. `RiskManager.max_safe_leverage()` clamps the
*requested* leverage down (never up) so the stop-loss distance always
stays safely inside the estimated liquidation distance. Don't disable or
work around this clamp.

**Why native stop orders matter:** on testnet/live, the stop-loss and
take-profit are placed as real `STOP_MARKET`/`TAKE_PROFIT_MARKET`
`reduceOnly` orders on the exchange the moment a position opens — not
just checked by our poll loop. A polled, software-only stop can lose a
race with a fast move between poll ticks (default every 5s); an
exchange-side order can't. Paper mode doesn't place real orders (nothing
to attach them to) — that's fine, since paper mode has no liquidation
risk to guard against in the first place.

**Recommended settings to start:**

| Parameter | Recommended start | Env var |
|---|---|---|
| Default leverage | **5x** | `FUTURES_LEVERAGE_DEFAULT=5` |
| Max leverage (hard cap) | **10x** while learning the system; raise later if you want | `FUTURES_MAX_LEVERAGE=10` |
| Mode | **paper**, then Binance Futures Testnet, then live | `FUTURES_MODE=paper` |

`FUTURES_MAX_LEVERAGE` defaults to 50 in this repo (matching what Binance
offers) so the leverage selector in the dashboard has full range — but
there is no obligation to actually use the high end of it. Treat 25–50x as
"available if you understand exactly what you're doing," not as a
starting point.
