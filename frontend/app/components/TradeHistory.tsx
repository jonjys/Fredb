import { TradeOut } from "@/lib/types";
import TradeListItem from "@/components/TradeListItem";

export default function TradeHistory({ trades }: { trades: TradeOut[] | null }) {
  const list = trades ?? [];
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-muted">Trade history</span>
        {list.length > 0 && <span className="text-xs text-muted">{list.length} trades</span>}
      </div>
      <div className="max-h-[32rem] space-y-2 overflow-y-auto pr-1">
        {list.length === 0 && (
          <div className="py-10 text-center text-sm text-muted">No closed trades yet</div>
        )}
        {list.map((t) => (
          <TradeListItem
            key={t.id}
            trade={{
              id: t.id,
              symbol: t.symbol,
              side: t.side,
              entryPrice: t.entry_price,
              exitPrice: t.exit_price,
              qty: t.qty,
              pnlQuote: t.pnl_quote,
              pnlPct: t.pnl_pct,
              closeReason: t.close_reason,
              closedAt: t.closed_at,
            }}
          />
        ))}
      </div>
    </div>
  );
}
