import { PerformanceStatsOut } from "@/lib/types";
import { fmtMoney, pnlColor } from "@/lib/format";

function Stat({
  label,
  value,
  valueClass,
  hint,
}: {
  label: string;
  value: string;
  valueClass?: string;
  hint?: string;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-bold tabular-nums ${valueClass ?? "text-white"}`}>
        {value}
      </div>
      {hint && <div className="text-[10px] text-muted">{hint}</div>}
    </div>
  );
}

/** The run of consecutive wins (or losses) the bot is on right now. */
function StreakBanner({ streak }: { streak: number }) {
  if (streak === 0) {
    return (
      <div className="rounded-lg border border-border bg-surfaceAlt px-4 py-3 text-center text-sm text-muted">
        No closed trades yet — the streak shows up here once the bot has results.
      </div>
    );
  }

  const winning = streak > 0;
  const count = Math.abs(streak);
  // Cap the rendered chips so a long run stays on one line; the numeric
  // label carries the real count.
  const chips = Array.from({ length: Math.min(count, 8) });

  return (
    <div
      className={`rounded-lg border px-4 py-3 ${
        winning ? "border-positive/40 bg-positive/10" : "border-negative/40 bg-negative/10"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className={`text-sm font-bold ${winning ? "text-positive" : "text-negative"}`}>
          {count} {winning ? (count === 1 ? "WIN" : "WINS") : count === 1 ? "LOSS" : "LOSSES"} IN A ROW
        </div>
        <div className="flex flex-wrap gap-1">
          {chips.map((_, i) => (
            <span
              key={i}
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                winning ? "bg-positive/25 text-positive" : "bg-negative/25 text-negative"
              }`}
            >
              {winning ? "W" : "L"}
            </span>
          ))}
          {count > 8 && (
            <span className={`text-[10px] font-bold ${winning ? "text-positive" : "text-negative"}`}>
              +{count - 8}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function DirectionRow({
  label,
  trades,
  winRate,
}: {
  label: string;
  trades: number;
  winRate: number | null;
}) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted">
        {label} <span className="text-white/60">({trades})</span>
      </span>
      <span className="font-semibold tabular-nums text-white">
        {winRate === null ? "—" : `${winRate.toFixed(0)}% win`}
      </span>
    </div>
  );
}

export default function PerformancePanel({ stats }: { stats: PerformanceStatsOut | null }) {
  if (!stats) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="text-xs uppercase tracking-wide text-muted">Performance</div>
        <div className="py-6 text-center text-sm text-muted">Loading…</div>
      </div>
    );
  }

  const hasTrades = stats.total_trades > 0;
  const profitFactorLabel =
    stats.profit_factor === null ? "—" : stats.profit_factor.toFixed(2);

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-muted">Performance</span>
        {hasTrades && (
          <span className="text-xs text-muted">{stats.total_trades} closed trades</span>
        )}
      </div>

      <StreakBanner streak={stats.current_streak} />

      <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat
          label="Win rate"
          value={hasTrades ? `${stats.win_rate_pct.toFixed(1)}%` : "—"}
          valueClass={
            !hasTrades ? "text-muted" : stats.win_rate_pct >= 50 ? "text-positive" : "text-negative"
          }
          hint={hasTrades ? `${stats.wins}W / ${stats.losses}L` : undefined}
        />
        <Stat
          label="Net P&L"
          value={`$${fmtMoney(stats.net_pnl_quote)}`}
          valueClass={pnlColor(stats.net_pnl_quote)}
        />
        <Stat
          label="Profit factor"
          value={profitFactorLabel}
          valueClass={
            stats.profit_factor === null
              ? "text-muted"
              : stats.profit_factor >= 1
                ? "text-positive"
                : "text-negative"
          }
          hint="gross win ÷ gross loss"
        />
        <Stat
          label="Best streak"
          value={hasTrades ? `${stats.best_win_streak}` : "—"}
          hint="consecutive wins"
        />
      </div>

      {hasTrades && (
        <>
          <div className="mt-4 grid grid-cols-2 gap-4 border-t border-border pt-3 sm:grid-cols-4">
            <Stat
              label="Avg win"
              value={`$${fmtMoney(stats.avg_win_quote)}`}
              valueClass="text-positive"
            />
            <Stat
              label="Avg loss"
              value={`$${fmtMoney(stats.avg_loss_quote)}`}
              valueClass="text-negative"
            />
            <Stat
              label="Best trade"
              value={`$${fmtMoney(stats.best_trade_quote)}`}
              valueClass="text-positive"
            />
            <Stat
              label="Worst trade"
              value={`$${fmtMoney(stats.worst_trade_quote)}`}
              valueClass="text-negative"
            />
          </div>

          {(stats.long_trades > 0 || stats.short_trades > 0) && (
            <div className="mt-3 space-y-1 border-t border-border pt-3">
              <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">
                By direction
              </div>
              <DirectionRow
                label="Long"
                trades={stats.long_trades}
                winRate={stats.long_win_rate_pct}
              />
              <DirectionRow
                label="Short"
                trades={stats.short_trades}
                winRate={stats.short_win_rate_pct}
              />
            </div>
          )}

          {stats.profit_factor !== null && stats.profit_factor < 1 && (
            <p className="mt-3 rounded-lg border border-negative/30 bg-negative/10 p-2 text-xs text-negative">
              Profit factor below 1.0 — losses currently outweigh wins overall, even at a{" "}
              {stats.win_rate_pct.toFixed(0)}% win rate. Worth reviewing before scaling size up.
            </p>
          )}
        </>
      )}
    </div>
  );
}
