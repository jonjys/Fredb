# Deployment Guide

Two independent deploys: **backend** (Railway or Render, a long-lived
process) and **frontend** (Vercel).

## Current live deployment

This project is currently deployed in **paper mode** (simulated wallet,
real market data, zero exchange risk):

- Backend (Railway): https://fredb-trading-bot-production.up.railway.app
  — running in the **europe-west4** region (moved from the default `sfo`
  region after Binance returned HTTP 451 for US-based requests)
- Frontend (Vercel): https://fredb-trading-bot-dashboard.vercel.app
  — auto-deploys on every push to `main` (Vercel project is git-connected,
  Root Directory set to `frontend`)

The bot's running/stopped state persists across redeploys (SQLite state on
a Railway Volume) — it does not reset to stopped on its own. `CORS_ORIGINS` on the backend and
`BACKEND_URL`/`DASHBOARD_API_TOKEN` on the frontend are already wired to
each other. To promote this deployment to testnet/live, follow steps 3–4
below and update the Railway environment variables via `railway variable
set` or the dashboard.

## 0. Before you deploy anything

- Generate a dashboard token: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- Keep `BOT_MODE=paper` for the first deploy. Confirm the whole pipeline
  works end-to-end before ever touching testnet or live keys.

## 1. Backend — Railway

1. Push this repo to GitHub.
2. In Railway: **New Project → Deploy from GitHub repo**, select the repo,
   set the **root directory to `backend`** (Railway auto-detects the
   `Dockerfile`).
3. Add a **Volume** mounted at `/app/data` — this is where `bot.db` and
   logs live; without it, positions don't survive a redeploy.
4. Set environment variables (Railway → Variables), at minimum:
   - `BOT_MODE=paper`
   - `EXCHANGE_ID=binance`
   - `SYMBOLS=BTC/USDT,ETH/USDT`
   - `DASHBOARD_API_TOKEN=<the secret you generated>`
   - `CORS_ORIGINS=https://<your-vercel-app>.vercel.app`
   - `DATABASE_PATH=data/bot.db`
   - (leave `BINANCE_API_KEY`/`SECRET` empty for paper mode)
5. Deploy. Railway assigns a public URL and injects `PORT` automatically —
   the Dockerfile's `CMD` already reads `$PORT`.
6. Verify: `curl https://<your-app>.up.railway.app/api/health` → `{"status":"ok"}`.

**Region note (important):** Binance blocks US IPs outright (HTTP 451
"Service unavailable from a restricted location"). Both Railway's and
Render's *default* regions are in the US (`sfo`/`us-west2` on Railway,
Oregon on Render) — deploying with defaults will hit this immediately.
This repo's configs already default to Europe:
`backend/railway.json` pins `europe-west4-drams3a`, and
`backend/render.yaml` sets `region: frankfurt`. If you deploy manually
and skip these configs, explicitly select a European region yourself
(Railway: `railway service scale eu-west=1 <your-current-region>=0`;
Render: pick `Frankfurt` in the dashboard). Symptom to watch for in the
live log: `Exchange call failed ... 451 ... restricted location`.
Alternatives if you must run from the US: `EXCHANGE_ID=binanceus` (a
different exchange with different pairs/liquidity) or `EXCHANGE_ID=coinbase`.

### Alternative — Render

1. **New → Blueprint**, point it at this repo — it will pick up
   `backend/render.yaml` automatically (adjust `dockerContext`/paths if you
   deploy from the repo root instead of `backend/`).
2. Render provisions a persistent disk at `/app/data` per the blueprint.
3. Set the same environment variables as above in the Render dashboard
   (the blueprint auto-generates `DASHBOARD_API_TOKEN` for you — copy it
   from Render's dashboard into the frontend's env vars).
4. Health check path is pre-configured to `/api/health`.

## 2. Frontend — Vercel

1. In Vercel: **Add New → Project**, import the repo, set **root directory
   to `frontend`**. Vercel auto-detects Next.js.
2. Environment variables (Vercel → Settings → Environment Variables) —
   **do not prefix these with `NEXT_PUBLIC_`**, they must stay server-only:
   - `BACKEND_URL=https://<your-railway-or-render-backend-url>`
   - `DASHBOARD_API_TOKEN=<same secret as the backend>`
3. Deploy. Once live, go back to the backend's `CORS_ORIGINS` env var and
   set it to the real Vercel URL, then redeploy the backend.
4. Open the Vercel URL — you should see the dashboard, mode badge showing
   `PAPER`, equity around your configured starting paper balance.

## 3. Promote to testnet

1. Create Binance Spot Testnet keys: https://testnet.binance.vision/
   (log in with GitHub, generate a key pair — these are test-only, no real
   funds involved).
2. Backend env vars: `BOT_MODE=testnet`, `BINANCE_API_KEY`/`BINANCE_API_SECRET`
   set to the testnet keys.
3. Redeploy. Confirm trades execute against the sandbox (ccxt's
   `set_sandbox_mode(True)` routes all calls to Binance's testnet host).
4. Let it run for several days. Watch the dashboard's trade history and
   equity curve. Do not go live until you're satisfied with behavior across
   different market conditions (trending, choppy, low-volume).

## 4. Promote to live (real money)

Read [API_KEY_SECURITY.md](API_KEY_SECURITY.md) fully first.

1. Create a **read-only** Binance API key first. Point `BOT_MODE=live` at
   it temporarily just to confirm balance/market-data fetches work — the
   bot will fail to place orders (expected) but this validates
   connectivity and permissions boundaries before trading is possible.
2. Create a second, **trading-enabled** key (spot trading only — leave
   withdrawals disabled, always). Restrict it by IP if your hosting
   provider gives you a static egress IP (Render does on paid plans;
   Railway offers static IPs as an add-on).
3. Swap the backend's key env vars to the trading key, set `BOT_MODE=live`.
4. Start with `MAX_RISK_PER_TRADE_PCT=1`, `MAX_CONCURRENT_POSITIONS=2-3`,
   and a small real balance (see [RISK_SETTINGS.md](RISK_SETTINGS.md)) —
   size the account for what you can afford to lose while you observe live
   behavior.
5. Watch the dashboard closely for the first days. Use the **Stop** button
   liberally (blocks new entries, keeps managing open ones) and
   **Emergency Kill** (closes everything immediately) if anything looks
   wrong.

## Updating deployments

Both Railway/Render and Vercel redeploy automatically on push to the
branch they're tracking. The backend's SQLite state persists across
redeploys as long as the volume/disk stays attached — don't delete or
resize the volume without checking you don't need the data.
