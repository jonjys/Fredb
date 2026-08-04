import { TradeOut } from "@/lib/types";
import { fmtMoney, fmtPct, fmtTime, pnlColor } from "@/lib/format";

export default function TradeHistory({ trades }: { trades: TradeOut[] | null }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 text-xs uppercase tracking-wide text-muted">Trade history</div>
      <div className="max-h-96 overflow-y-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-xs uppercase text-muted">
              <th className="pb-2 pr-4">Symbol</th>
              <th className="pb-2 pr-4">Entry</th>
              <th className="pb-2 pr-4">Exit</th>
              <th className="pb-2 pr-4">Qty</th>
              <th className="pb-2 pr-4">P&L</th>
              <th className="pb-2 pr-4">Reason</th>
              <th className="pb-2 pr-4">Closed</th>
            </tr>
          </thead>
          <tbody>
            {(trades ?? []).length === 0 && (
              <tr>
                <td colSpan={7} className="py-6 text-center text-muted">
                  No closed trades yet
                </td>
              </tr>
            )}
            {(trades ?? []).map((t) => (
              <tr key={t.id} className="border-t border-border">
                <td className="py-2 pr-4 font-medium">{t.symbol}</td>
                <td className="py-2 pr-4">${fmtMoney(t.entry_price, 4)}</td>
                <td className="py-2 pr-4">${fmtMoney(t.exit_price, 4)}</td>
                <td className="py-2 pr-4">{t.qty.toFixed(6)}</td>
                <td className={`py-2 pr-4 ${pnlColor(t.pnl_quote)}`}>
                  ${fmtMoney(t.pnl_quote)} ({fmtPct(t.pnl_pct)})
                </td>
                <td className="py-2 pr-4 text-muted">{t.close_reason}</td>
                <td className="py-2 pr-4 text-muted">{fmtTime(t.closed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
