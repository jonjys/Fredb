"use client";

import { usePoll } from "@/lib/usePoll";
import { OrderBookData } from "@/lib/types";
import { fmtMoney } from "@/lib/format";

/** Bid/ask depth ladder, paired price-level-by-price-level like a real
 * exchange order book screen: amount, then price, then a depth bar showing
 * relative size — best bid and best ask on the same row. */
export default function OrderBookLadder({
  orderBookPath,
  rows = 8,
  pollMs = 3000,
}: {
  orderBookPath: string;
  rows?: number;
  pollMs?: number;
}) {
  const { data: book } = usePoll<OrderBookData>(orderBookPath, pollMs);

  if (!book || (book.bids.length === 0 && book.asks.length === 0)) {
    return <div className="py-6 text-center text-sm text-muted">Loading order book…</div>;
  }

  const bids = book.bids.slice(0, rows);
  const asks = book.asks.slice(0, rows);
  const maxQty = Math.max(...bids.map((b) => b[1]), ...asks.map((a) => a[1]), 0.0001);
  const decimals = (bids[0]?.[0] ?? asks[0]?.[0] ?? 1) < 10 ? 4 : 2;

  const rowCount = Math.max(bids.length, asks.length);

  return (
    <div className="font-mono text-xs">
      <div className="mb-1.5 grid grid-cols-4 gap-2 text-[10px] uppercase tracking-wide text-muted">
        <span className="text-right">Amount</span>
        <span className="text-right text-positive">Bid</span>
        <span className="text-left text-negative">Ask</span>
        <span className="text-left">Amount</span>
      </div>
      <div className="space-y-0.5">
        {Array.from({ length: rowCount }).map((_, i) => {
          const bid = bids[i];
          const ask = asks[i];
          const bidPct = bid ? (bid[1] / maxQty) * 100 : 0;
          const askPct = ask ? (ask[1] / maxQty) * 100 : 0;
          return (
            <div key={i} className="grid grid-cols-4 gap-2">
              <div className="relative text-right tabular-nums text-white/80">
                <div className="absolute inset-y-0 right-0 bg-positive/10" style={{ width: `${bidPct}%` }} />
                <span className="relative">{bid ? bid[1].toFixed(4) : ""}</span>
              </div>
              <div className="text-right tabular-nums font-semibold text-positive">
                {bid ? fmtMoney(bid[0], decimals) : ""}
              </div>
              <div className="text-left tabular-nums font-semibold text-negative">
                {ask ? fmtMoney(ask[0], decimals) : ""}
              </div>
              <div className="relative text-left tabular-nums text-white/80">
                <div className="absolute inset-y-0 left-0 bg-negative/10" style={{ width: `${askPct}%` }} />
                <span className="relative">{ask ? ask[1].toFixed(4) : ""}</span>
              </div>
            </div>
          );
        })}
      </div>
      {bids[0] && asks[0] && (
        <div className="mt-2 border-t border-border pt-2 text-center text-[10px] text-muted">
          spread {fmtMoney(asks[0][0] - bids[0][0], decimals)} (
          {(((asks[0][0] - bids[0][0]) / bids[0][0]) * 100).toFixed(3)}%)
        </div>
      )}
    </div>
  );
}
