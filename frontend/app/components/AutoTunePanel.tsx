// app/components/AutoTunePanel.tsx
"use client";

import { useState } from "react";
import { AutotuneStatusOut } from "@/lib/types";
import { fmtTime } from "@/lib/format";

function fmtPf(pf: number | null): string {
  return pf === null || pf === undefined ? "—" : pf.toFixed(2);
}

/** Nightly TP grid-search status — deliberately suggest-only unless
 * auto_apply is explicitly turned on server-side (see app/autotune.py):
 * a 14-day sample is small and noisy, so this surfaces the recommendation
 * for a human to act on rather than silently rewriting live risk settings. */
export default function AutoTunePanel({
  status,
  onRunNow,
}: {
  status: AutotuneStatusOut | null | undefined;
  onRunNow: () => Promise<void>;
}) {
  const [running, setRunning] = useState(false);

  async function handleRunNow() {
    setRunning(true);
    try {
      await onRunNow();
    } finally {
      setRunning(false);
    }
  }

  if (!status) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">
        AutoTune status unavailable.
      </div>
    );
  }

  const hasSuggestion = status.suggested_tp !== null && status.suggested_tp !== status.current_tp;

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-muted">AutoTune</span>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
              status.auto_apply
                ? "bg-yellow-500/15 text-yellow-400"
                : "bg-surfaceAlt text-muted"
            }`}
          >
            {status.auto_apply ? "AUTO-APPLY" : "SUGGEST-ONLY"}
          </span>
          <button
            onClick={handleRunNow}
            disabled={running || !status.enabled}
            className="rounded-lg border border-border bg-surfaceAlt px-3 py-1 text-xs font-semibold text-white hover:border-accent/50 disabled:opacity-50"
          >
            {running ? "Running…" : "Run now"}
          </button>
        </div>
      </div>

      <p className="text-sm text-white">
        Nightly grid-search over the last {status.lookback_days}d at {status.hour_utc}:00 UTC —
        tests alternative take_profit_pct values and reports whether one would have scored a
        meaningfully better profit factor.
      </p>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-lg bg-surfaceAlt p-2.5">
          <div className="text-[10px] uppercase tracking-wide text-muted">Current TP</div>
          <div className="mt-0.5 text-lg font-bold tabular-nums text-white">
            {status.current_tp?.toFixed(2) ?? "—"}%
          </div>
          <div className="text-[10px] text-muted">PF {fmtPf(status.current_pf)}</div>
        </div>
        <div className="rounded-lg bg-surfaceAlt p-2.5">
          <div className="text-[10px] uppercase tracking-wide text-muted">Suggested TP</div>
          <div className={`mt-0.5 text-lg font-bold tabular-nums ${hasSuggestion ? "text-accent" : "text-muted"}`}>
            {status.suggested_tp !== null ? `${status.suggested_tp.toFixed(2)}%` : "—"}
          </div>
          <div className="text-[10px] text-muted">PF {fmtPf(status.suggested_pf)}</div>
        </div>
      </div>

      {hasSuggestion && (
        <div className="mt-3 rounded-lg bg-accent/10 p-2.5 text-xs text-accent">
          AutoTune: TP {status.current_tp?.toFixed(2)}% → {status.suggested_tp?.toFixed(2)}% because PF
          {" "}
          {fmtPf(status.current_pf)} → {fmtPf(status.suggested_pf)}.
          {status.applied ? " Applied automatically." : " Not applied — review and update take_profit_pct manually if you agree."}
        </div>
      )}

      {status.ran_at && (
        <div className="mt-2 text-[10px] text-muted">Last run: {fmtTime(status.ran_at)}</div>
      )}
      {status.note && <div className="mt-1 truncate text-[10px] text-muted" title={status.note}>{status.note}</div>}
    </div>
  );
}
