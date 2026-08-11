import { fmtMoney, fmtPct } from "@/lib/format";
import { LiveOrderRowData } from "@/components/LiveOrdersPanel";

/** Dense mobile replacement for the wide desktop positions table — one
 * card per position, everything that matters in a glance instead of a
 * table you have to scroll sideways to read on a phone. */
export default function MobilePositionCard({ position }: { position: LiveOrderRowData }) {
  const pnlPct = position.unrealizedPnlPct;
  const inProfit = pnlPct !== null && pnlPct >= 0;
  const pnlGlowClass =
    pnlPct === null
      ? "text-muted"
      : inProfit
        ? "text-positive drop-shadow-[0_0_8px_rgba(34,197,94,0.55)]"
        : "text-negative/80";

  return (
    <div className="rounded-xl border border-border bg-surface p-3.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="font-semibold text-white">{position.symbol}</span>
          {position.leverage !== undefined && (
            <span className="rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
              {position.leverage}x
            </span>
          )}
          <span
            className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
              position.side === "short"
                ? "border-negative/30 bg-negative/10 text-negative"
                : "border-positive/30 bg-positive/10 text-positive"
            }`}
          >
            {position.side}
          </span>
        </div>
        <div className={`text-lg font-bold tabular-nums ${pnlGlowClass}`}>
          {pnlPct === null ? "—" : fmtPct(pnlPct)}
        </div>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2 border-t border-border pt-2 font-mono text-[11px]">
        <div>
          <div className="text-muted">Entry</div>
          <div className="text-white">{fmtMoney(position.entryPrice, 4)}</div>
        </div>
        <div>
          <div className="text-negative/80">Stop</div>
          <div className="text-negative">{fmtMoney(position.stopLossPrice, 4)}</div>
        </div>
        <div>
          <div className="text-positive/80">Target</div>
          <div className="text-positive">{fmtMoney(position.takeProfitPrice, 4)}</div>
        </div>
      </div>

      <div className="mt-1.5 text-right font-mono text-[10px] text-muted">
        {position.unrealizedPnlQuote !== null ? `$${fmtMoney(position.unrealizedPnlQuote)}` : "—"}
      </div>
    </div>
  );
}
