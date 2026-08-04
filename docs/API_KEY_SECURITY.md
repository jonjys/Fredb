# API Key Security

## Golden rules

1. **Never enable withdrawal permission** on any bot API key. Ever. A
   trading bot needs to read balances, read market data, and place/cancel
   spot orders — nothing else. If a key or a server is ever compromised,
   the blast radius without withdrawal permission is "an attacker can
   trade badly with your funds," not "an attacker can drain your account."
2. **Keys live only in backend environment variables.** They are read once
   at process start ([backend/app/config.py](../backend/app/config.py))
   and never logged, never returned by any API endpoint, never sent to the
   frontend. The frontend doesn't hold exchange keys at all — see
   `frontend/app/lib/backend.ts` for how it proxies requests using a
   *separate* dashboard token instead.
3. **Two different secrets, two different jobs:**
   - `DASHBOARD_API_TOKEN` — authenticates the *frontend* to the *backend*.
     Compromise of this lets someone see your dashboard and press
     start/stop/kill. Annoying, not catastrophic.
   - `BINANCE_API_KEY`/`SECRET` (or Coinbase equivalent) — authenticates
     the *backend* to the *exchange*. This is the one that matters most.
4. **Never commit `.env` files.** Both `backend/.gitignore` and the repo
   root `.gitignore` already exclude `backend/.env` and `frontend/.env.local`.
   Only `*.env.example` files (with placeholder values) belong in git.

## Rollout order

Don't jump straight to a live trading key. Follow this sequence:

1. **Paper mode, no keys at all.** (`BOT_MODE=paper`) The bot uses public,
   unauthenticated market data and a fully simulated wallet. Zero exchange
   risk. Run this until you trust the strategy's behavior and the
   dashboard's controls (start/stop/kill/settings) all work as expected.
2. **Read-only key.** Create an API key on Binance with only "Enable
   Reading" checked. Point the bot at it (still `BOT_MODE=paper` or set
   `BOT_MODE=live` briefly just to test connectivity — order placement
   will correctly fail with a permissions error). This validates your key
   setup, IP restrictions, and that balance/ticker/OHLCV fetches work,
   without any possibility of the bot placing an order.
3. **Testnet key.** Binance Spot Testnet (https://testnet.binance.vision/)
   gives you a sandbox with fake funds and a fully functional order book.
   `BOT_MODE=testnet` routes ccxt through the sandbox host. Run for
   several days across different market conditions.
4. **Live, trading-enabled key, small balance.** Enable "Enable Spot &
   Margin Trading" (spot only — don't enable margin/futures). Restrict by
   IP address if your host supports a static egress IP. Fund the account
   with only what you're prepared to lose while you observe live
   performance. Scale up gradually, only after sustained good behavior.

## If you ever suspect a key is compromised

Revoke it immediately from the exchange's API management page — this
takes effect instantly and doesn't require redeploying anything. Then
rotate `DASHBOARD_API_TOKEN` too if you suspect the server itself was
compromised, since that key alone could be used to pause/resume/kill the
bot.
