import { fmtMoney, fmtPct, fmtTime, pnlColor } from "@/lib/format";
import PositionSparkline from "@/components/PositionSparkline";

export interface LiveOrderRowData {
  id: number;
  symbol: string;
  side: string;
  leverage?: number;
  entryPrice: number;
  currentPrice: number | null;
  stopLossPrice: number;
  takeProfitPrice: number;
  unrealizedPnlQuote: number | null;
  unrealizedPnlPct: number | null;
  openedAt: number;
  candlesPath: string;
}

/** One row per live order the bot is currently in, each with its own
 * recent-price chart — the "what is it actually doing right now" view
 * that a metrics-only positions table doesn't give you. */
export default function LiveOrdersPanel({ orders }: { orders: LiveOrderRowData[] }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-3 md:p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-muted">Live orders</span>
        {orders.length > 0 && <span className="text-xs text-muted">{orders.length} open</span>}
      </div>

      {orders.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
          </span>
          <div className="text-sm font-medium text-white/80">Flat right now</div>
          <div className="max-w-[26ch] text-xs text-muted">
            The bot is scanning the market for a setup — check Logs for live signal activity.
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {orders.map((o) => (
            <div key={o.id} className="rounded-lg border border-border bg-surfaceAlt/40 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-white">{o.symbol}</span>
                  <span
                    className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                      o.side === "short"
                        ? "border-negative/30 bg-negative/10 text-negative"
                        : "border-positive/30 bg-positive/10 text-positive"
                    }`}
                  >
                    {o.side}
                  </span>
                  {o.leverage !== undefined && (
                    <span className="rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                      {o.leverage}x
                    </span>
                  )}
                  <span className="text-xs text-muted">opened {fmtTime(o.openedAt)}</span>
                </div>
                <div className="text-right">
                  <div className={`font-mono text-sm font-bold tabular-nums ${pnlColor(o.unrealizedPnlQuote)}`}>
                    {o.unrealizedPnlQuote !== null ? `$${fmtMoney(o.unrealizedPnlQuote)}` : "—"}
                  </div>
                  <div className={`text-xs tabular-nums ${pnlColor(o.unrealizedPnlPct)}`}>
                    {o.unrealizedPnlPct !== null ? fmtPct(o.unrealizedPnlPct) : "—"}
                  </div>
                </div>
              </div>

              <div className="mt-2">
                <PositionSparkline
                  candlesPath={o.candlesPath}
                  entryPrice={o.entryPrice}
                  stopLossPrice={o.stopLossPrice}
                  takeProfitPrice={o.takeProfitPrice}
                  side={o.side}
                />
              </div>

              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-[10px] text-muted">
                <span>entry ${fmtMoney(o.entryPrice, 4)}</span>
                <span>now {o.currentPrice ? `$${fmtMoney(o.currentPrice, 4)}` : "—"}</span>
                <span className="text-negative">SL ${fmtMoney(o.stopLossPrice, 4)}</span>
                <span className="text-positive">TP ${fmtMoney(o.takeProfitPrice, 4)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
