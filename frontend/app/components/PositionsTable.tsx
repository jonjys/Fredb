import { PositionOut } from "@/lib/types";
import { fmtMoney, fmtPct, fmtTime, pnlColor } from "@/lib/format";

export default function PositionsTable({ positions }: { positions: PositionOut[] | null }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 text-xs uppercase tracking-wide text-muted">Open positions</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr className="text-xs uppercase text-muted">
              <th className="pb-2 pr-4">Symbol</th>
              <th className="pb-2 pr-4">Entry</th>
              <th className="pb-2 pr-4">Current</th>
              <th className="pb-2 pr-4">Qty</th>
              <th className="pb-2 pr-4">Stop loss</th>
              <th className="pb-2 pr-4">Take profit</th>
              <th className="pb-2 pr-4">Trailing</th>
              <th className="pb-2 pr-4">Unrealized P&L</th>
              <th className="pb-2 pr-4">Opened</th>
            </tr>
          </thead>
          <tbody>
            {(positions ?? []).length === 0 && (
              <tr>
                <td colSpan={9} className="py-6 text-center text-muted">
                  No open positions
                </td>
              </tr>
            )}
            {(positions ?? []).map((p) => (
              <tr key={p.id} className="border-t border-border">
                <td className="py-2 pr-4 font-medium">{p.symbol}</td>
                <td className="py-2 pr-4">${fmtMoney(p.entry_price, 4)}</td>
                <td className="py-2 pr-4">{p.current_price ? `$${fmtMoney(p.current_price, 4)}` : "—"}</td>
                <td className="py-2 pr-4">{p.qty.toFixed(6)}</td>
                <td className="py-2 pr-4 text-negative">${fmtMoney(p.stop_loss_price, 4)}</td>
                <td className="py-2 pr-4 text-positive">${fmtMoney(p.take_profit_price, 4)}</td>
                <td className="py-2 pr-4">{p.trailing_active ? "Active" : "—"}</td>
                <td className={`py-2 pr-4 ${pnlColor(p.unrealized_pnl_quote)}`}>
                  {p.unrealized_pnl_quote !== null ? `$${fmtMoney(p.unrealized_pnl_quote)}` : "—"}{" "}
                  {p.unrealized_pnl_pct !== null && `(${fmtPct(p.unrealized_pnl_pct)})`}
                </td>
                <td className="py-2 pr-4 text-muted">{fmtTime(p.opened_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
