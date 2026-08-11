import { fmtMoney, pnlColor } from "@/lib/format";

export interface PerformanceGridData {
  winRatePct: number | null;
  netPnlQuote: number | null;
  activePositionsLabel: string; // e.g. "2 / 3" or "2 / 3 · $84.20 margin"
  running: boolean;
  killSwitch: boolean;
  killSwitchReason?: string;
  throttlePaused?: boolean;
}

/** The four numbers that answer "is this thing working" in one glance,
 * pinned above everything else — separate from PerformancePanel's fuller
 * breakdown, which is detail you check once this row says something's
 * off. */
export default function PerformanceGrid({ data }: { data: PerformanceGridData }) {
  const statusLabel = data.killSwitch ? "KILLED" : data.throttlePaused ? "PAUSED" : data.running ? "LIVE" : "STOPPED";
  const statusColor = data.killSwitch
    ? "text-negative"
    : data.throttlePaused
      ? "text-yellow-400"
      : data.running
        ? "text-positive"
        : "text-muted";
  const dotColor = data.killSwitch
    ? "bg-negative"
    : data.throttlePaused
      ? "bg-yellow-500"
      : data.running
        ? "bg-positive"
        : "bg-muted";

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4 md:gap-4">
      <div className="rounded-xl border border-border bg-surface p-3 md:p-4">
        <div className="text-[10px] uppercase tracking-wide text-muted">Win rate</div>
        <div
          className={`mt-1 text-lg font-bold tabular-nums md:text-2xl ${
            data.winRatePct === null ? "text-muted" : data.winRatePct >= 50 ? "text-positive" : "text-negative"
          }`}
        >
          {data.winRatePct === null ? "—" : `${data.winRatePct.toFixed(1)}%`}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-3 md:p-4">
        <div className="text-[10px] uppercase tracking-wide text-muted">Net profit</div>
        <div className={`mt-1 text-lg font-bold tabular-nums md:text-2xl ${pnlColor(data.netPnlQuote)}`}>
          {data.netPnlQuote === null ? "—" : `$${fmtMoney(data.netPnlQuote)}`}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-3 md:p-4">
        <div className="text-[10px] uppercase tracking-wide text-muted">Active positions</div>
        <div className="mt-1 truncate text-lg font-bold tabular-nums text-white md:text-2xl">
          {data.activePositionsLabel}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-3 md:p-4">
        <div className="text-[10px] uppercase tracking-wide text-muted">Bot status</div>
        <div className={`mt-1 flex items-center gap-2 text-lg font-bold md:text-2xl ${statusColor}`}>
          <span className={`relative flex h-2.5 w-2.5 shrink-0`}>
            {(data.running || data.throttlePaused) && !data.killSwitch && (
              <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${dotColor} opacity-60`} />
            )}
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dotColor}`} />
          </span>
          {statusLabel}
        </div>
        {data.killSwitch && data.killSwitchReason && (
          <div className="mt-1 truncate text-[10px] text-negative" title={data.killSwitchReason}>
            {data.killSwitchReason}
          </div>
        )}
        {!data.killSwitch && data.throttlePaused && (
          <div className="mt-1 text-[10px] text-yellow-400">consecutive-loss circuit breaker</div>
        )}
      </div>
    </div>
  );
}
