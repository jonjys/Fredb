"use client";

import { useState } from "react";
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
  const [symbol, setSymbol] = useState(symbols[0] ?? "");
  const encoded = encodeURIComponent(symbol);
  const ohlcvPath = `${ohlcvBasePath}?symbol=${encoded}&timeframe=1m&limit=120`;
  const orderBookPath = `${orderBookBasePath}?symbol=${encoded}&limit=8`;

  const { data: bars } = usePoll<OhlcvBar[]>(ohlcvPath, 5000);
  const last = bars && bars.length > 0 ? bars[bars.length - 1] : null;
  const first = bars && bars.length > 0 ? bars[0] : null;
  const sessionChangePct = last && first && first.open ? ((last.close - first.open) / first.open) * 100 : null;

  if (!symbol) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4 text-center text-sm text-muted">
        No symbols available yet.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded-lg border border-border bg-surfaceAlt px-3 py-1.5 text-sm font-semibold text-white"
          >
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {last && (
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-lg font-bold text-white">
                ${fmtMoney(last.close, last.close < 10 ? 4 : 2)}
              </span>
              {sessionChangePct !== null && (
                <span className={`text-xs font-semibold ${sessionChangePct >= 0 ? "text-positive" : "text-negative"}`}>
                  {sessionChangePct >= 0 ? "+" : ""}
                  {sessionChangePct.toFixed(2)}% (this window)
                </span>
              )}
            </div>
          )}
        </div>
        <span className="text-[10px] uppercase tracking-wide text-muted">1m candles · live order book</span>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_260px]">
        <div className="overflow-x-auto">
          <CandlestickChart ohlcvPath={ohlcvPath} />
        </div>
        <div className="border-t border-border pt-3 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0">
          <OrderBookLadder orderBookPath={orderBookPath} />
        </div>
      </div>
    </div>
  );
}
