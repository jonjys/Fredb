import { StatusResponse } from "@/lib/types";
import { fmtMoney, fmtPct, pnlColor } from "@/lib/format";

function Stat({ label, value, sub, subColor }: { label: string; value: string; sub?: string; subColor?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
      {sub && <div className={`mt-1 text-sm ${subColor ?? "text-muted"}`}>{sub}</div>}
    </div>
  );
}

export default function BalanceCard({ status }: { status: StatusResponse | null }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Stat label="Portfolio value" value={`$${fmtMoney(status?.equity)}`} />
      <Stat label="Free balance" value={`$${fmtMoney(status?.quote_balance)}`} />
      <Stat
        label="Daily P&L"
        value={`$${fmtMoney(status?.daily_pnl)}`}
        sub={fmtPct(status?.daily_pnl_pct)}
        subColor={pnlColor(status?.daily_pnl)}
      />
      <Stat
        label="Open positions"
        value={`${status?.open_positions_count ?? 0} / ${status?.max_concurrent_positions ?? "—"}`}
      />
    </div>
  );
}
