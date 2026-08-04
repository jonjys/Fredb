# Automated Scalping Trading Bot

A production-oriented, 24/7 automated crypto trading bot with a live web
dashboard. Backend runs continuously on a server (not tied to a browser
tab); frontend is a Next.js dashboard for monitoring and control.

**⚠️ This trades with real money if you configure it to (`BOT_MODE=live`).
Read [docs/RISK_SETTINGS.md](docs/RISK_SETTINGS.md) and
[docs/API_KEY_SECURITY.md](docs/API_KEY_SECURITY.md) before doing that.
Always start in `paper` mode.**

## Architecture

```
                         ┌─────────────────────────┐
                         │   Binance / Coinbase     │
                         │   (via ccxt, unified)    │
                         └────────────▲─────────────┘
                                      │ REST (retrying, rate-limited)
                         ┌────────────┴─────────────┐
                         │   Backend (Python)        │
                         │   FastAPI + asyncio loop  │
                         │   - strategy.py (signals) │
                         │   - risk.py (sizing/kill) │
                         │   - bot.py (orchestrator) │
                         │   - SQLite (state_store)  │
                         │   hosted on Railway/Render│
                         └────────────▲─────────────┘
                                      │ REST, Bearer token
                         ┌────────────┴─────────────┐
                         │  Next.js server routes    │
                         │  (app/api/* — proxy,      │
                         │   holds the secret token) │
                         │  hosted on Vercel         │
                         └────────────▲─────────────┘
                                      │ same-origin fetch
                         ┌────────────┴─────────────┐
                         │  Browser dashboard (React) │
                         └───────────────────────────┘
```

- **Backend** ([backend/](backend/)) — Python, [ccxt](https://github.com/ccxt/ccxt)
  for exchange access (Binance primary, Coinbase secondary, more exchanges
  are a one-line config change away), FastAPI for the control API, an
  asyncio loop that ticks every few seconds to manage positions and look
  for new entries. State (positions, trades, equity, running/kill-switch
  flags) is persisted to SQLite so a restart resumes exactly where it left
  off. Runs as a long-lived process — deploy it to Railway or Render, not a
  serverless platform.
- **Frontend** ([frontend/](frontend/)) — Next.js (App Router) + Tailwind,
  deployed on Vercel. The browser never talks to the backend directly or
  holds any secret: it calls this app's own `/api/*` route handlers, which
  run server-side on Vercel and attach the bot's API token from an
  environment variable before forwarding to the backend. Exchange API keys
  live only on the backend and are never sent to the frontend at all.

## Strategy

Long-only EMA(9/21) crossover + RSI(14) momentum filter + Bollinger Band
overextension guard, evaluated on 1-minute candles (see
[backend/app/strategy.py](backend/app/strategy.py)). Exits are a hard
ATR-based stop-loss, a take-profit trigger that then hands off to a
trailing stop so winners can run
([backend/app/bot.py](backend/app/bot.py) `_manage_position`). This is a
starting point, not a guarantee of profitability — see
[docs/RISK_SETTINGS.md](docs/RISK_SETTINGS.md).

## Quick start (local, paper mode)

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # defaults to BOT_MODE=paper, no keys needed
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env.local    # point BACKEND_URL at http://localhost:8000
npm run dev
```

Open http://localhost:3000, click **Start**, and watch it paper-trade
against real live market data with a simulated wallet.

Run the backend test suite:

```bash
cd backend && source .venv/bin/activate
pip install pytest && pytest -q
```

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for step-by-step Railway/Render
+ Vercel instructions.

## Security & going live

See [docs/API_KEY_SECURITY.md](docs/API_KEY_SECURITY.md) for the
recommended read-only → trading-enabled key rollout, and
[docs/RISK_SETTINGS.md](docs/RISK_SETTINGS.md) for recommended starting
risk parameters.

## Repository layout

```
backend/    FastAPI app, trading engine, ccxt integration, tests
frontend/   Next.js dashboard (App Router, Tailwind, Recharts)
docs/       Deployment and risk/security guides
```
