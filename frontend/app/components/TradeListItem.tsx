import { fmtMoney, fmtPct, fmtTime, pnlColor } from "@/lib/format";

export interface TradeListItemData {
  id: number;
  symbol: string;
  side: string;
  entryPrice: number;
  exitPrice: number;
  qty: number;
  pnlQuote: number;
  pnlPct: number;
  closeReason: string;
  closedAt: number;
  leverage?: number;
}

const REASON_STYLES: Record<string, string> = {
  stop_loss: "bg-negative/15 text-negative border-negative/30",
  trailing_stop: "bg-positive/15 text-positive border-positive/30",
  emergency_kill: "bg-negative/20 text-negative border-negative/40",
};

function reasonLabel(reason: string): string {
  return reason.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function TradeListItem({ trade }: { trade: TradeListItemData }) {
  const win = trade.pnlQuote >= 0;
  return (
    <div
      className={`relative overflow-hidden rounded-xl border border-border bg-surface p-4 pl-5 ${
        win ? "before:bg-positive" : "before:bg-negative"
      } before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:content-['']`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-semibold text-white">{trade.symbol}</span>
            <span
              className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                trade.side === "short"
                  ? "border-negative/30 bg-negative/10 text-negative"
                  : "border-positive/30 bg-positive/10 text-positive"
              }`}
            >
              {trade.side || "long"}
            </span>
            {trade.leverage !== undefined && (
              <span className="shrink-0 rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                {trade.leverage}x
              </span>
            )}
          </div>
          <div className="mt-1 whitespace-nowrap font-mono text-xs text-muted">
            {fmtMoney(trade.entryPrice, 4)} <span className="text-white/40">→</span>{" "}
            {fmtMoney(trade.exitPrice, 4)}
          </div>
        </div>

        <div className="shrink-0 text-right">
          <div className={`whitespace-nowrap text-lg font-bold tabular-nums ${pnlColor(trade.pnlQuote)}`}>
            {trade.pnlQuote >= 0 ? "+" : ""}
            {fmtMoney(trade.pnlQuote)}
          </div>
          <div className={`whitespace-nowrap text-sm font-semibold tabular-nums ${pnlColor(trade.pnlPct)}`}>
            {fmtPct(trade.pnlPct)}
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="text-muted">Qty {trade.qty.toFixed(6)}</span>
          {trade.closeReason && (
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                REASON_STYLES[trade.closeReason] ?? "border-border bg-surfaceAlt text-muted"
              }`}
            >
              {reasonLabel(trade.closeReason)}
            </span>
          )}
        </div>
        <span className="text-muted">{fmtTime(trade.closedAt)}</span>
      </div>
    </div>
  );
}
