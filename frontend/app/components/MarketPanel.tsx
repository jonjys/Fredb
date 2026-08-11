"use client";

import { useEffect, useState } from "react";
import { usePoll } from "@/lib/usePoll";
import { OhlcvBar } from "@/lib/types";
import { fmtMoney } from "@/lib/format";
import CandlestickChart from "@/components/CandlestickChart";
import OrderBookLadder from "@/components/OrderBookLadder";

/** Live candlestick + order book for one symbol at a time, the way a real
 * exchange screen shows a market — separate from the bot's own positions,
 * this is "what the market is doing right now", not "what the bot did". */
export default function MarketPanel({
  symbols,
  ohlcvBasePath,
  orderBookBasePath,
}: {
  symbols: string[];
  ohlcvBasePath: string; // e.g. "/api/market/ohlcv" or "/api/futures/market/ohlcv"
  orderBookBasePath: string;
}) {
  const [symbol, setSymbol] = useState("");

  // `symbols` arrives async (it comes from the status poll) — the very
  // first render always has an empty list, and useState's initializer only
  // runs once, so it can never pick up a real symbol on its own. Adopt the
  // first symbol once the list loads, and re-adopt if the current pick
  // drops out of a dynamic (auto-rotating) symbol universe.
  useEffect(() => {
    if (symbols.length > 0 && !symbols.includes(symbol)) {
      setSymbol(symbols[0]);
    }
  }, [symbols, symbol]);

  const encoded = symbol ? encodeURIComponent(symbol) : "";
  const ohlcvPath = symbol ? `${ohlcvBasePath}?symbol=${encoded}&timeframe=1m&limit=120` : null;
  const orderBookPath = symbol ? `${orderBookBasePath}?symbol=${encoded}&limit=8` : null;

  const { data: bars } = usePoll<OhlcvBar[]>(ohlcvPath, 5000);
  const last = bars && bars.length > 0 ? bars[bars.length - 1] : null;
  const first = bars && bars.length > 0 ? bars[0] : null;
  const sessionChangePct = last && first && first.open ? ((last.close - first.open) / first.open) * 100 : null;

  if (!symbol || !ohlcvPath || !orderBookPath) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4 text-center text-sm text-muted">
        Waiting for symbols…
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-3 md:p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 md:mb-3 md:gap-3">
        <div className="flex flex-wrap items-center gap-2 md:gap-3">
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded-lg border border-border bg-surfaceAlt px-2.5 py-1.5 text-xs font-semibold text-white md:px-3 md:text-sm"
          >
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {last && (
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-base font-bold text-white md:text-lg">
                ${fmtMoney(last.close, last.close < 10 ? 4 : 2)}
              </span>
              {sessionChangePct !== null && (
                <span className={`text-xs font-semibold ${sessionChangePct >= 0 ? "text-positive" : "text-negative"}`}>
                  {sessionChangePct >= 0 ? "+" : ""}
                  {sessionChangePct.toFixed(2)}%
                </span>
              )}
            </div>
          )}
        </div>
        <span className="hidden text-[10px] uppercase tracking-wide text-muted sm:inline">
          1m candles · live order book
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 md:gap-4 lg:grid-cols-[1fr_260px]">
        <div className="overflow-x-auto">
          <CandlestickChart ohlcvPath={ohlcvPath} height={200} />
        </div>
        <div className="border-t border-border pt-3 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0">
          <OrderBookLadder orderBookPath={orderBookPath} rows={6} />
        </div>
      </div>
    </div>
  );
}
