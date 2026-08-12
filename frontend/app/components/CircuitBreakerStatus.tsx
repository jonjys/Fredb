// app/components/CircuitBreakerStatus.tsx
"use client";

import { useEffect, useState } from "react";

// Mirrors backend/app/config.py's consecutive_loss_threshold /
// consecutive_loss_reduced_trades defaults — not exposed over the API since
// it's a fixed risk-engine constant, not something the dashboard can change.
const LOSS_THRESHOLD = 4;

export interface CircuitBreakerStatusData {
  consecutiveLosses: number;
  throttlePausedUntil: number; // unix seconds; 0 = not paused
  reducedSizeTradesRemaining: number;
}

function fmtCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Quick-glance state of the consecutive-loss circuit breaker, surfaced
 * under Settings so a paused bot never reads as a silently broken one. */
export default function CircuitBreakerStatus({ data }: { data: CircuitBreakerStatusData }) {
  const [now, setNow] = useState(() => Date.now() / 1000);

  const isPaused = data.throttlePausedUntil > now;

  useEffect(() => {
    if (!isPaused) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [isPaused]);

  const isReducedSize = !isPaused && data.reducedSizeTradesRemaining > 0;
  const statusLabel = isPaused ? "PAUSED" : isReducedSize ? "REDUCED SIZE" : "ARMED";
  const statusColor = isPaused ? "text-negative" : isReducedSize ? "text-yellow-400" : "text-positive";
  const dotColor = isPaused ? "bg-negative" : isReducedSize ? "bg-yellow-500" : "bg-positive";

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wide text-muted">Circuit breaker</div>
        <div className={`flex items-center gap-1.5 text-xs font-bold ${statusColor}`}>
          <span className="relative flex h-2 w-2 shrink-0">
            {isPaused && (
              <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${dotColor} opacity-60`} />
            )}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${dotColor}`} />
          </span>
          {statusLabel}
        </div>
      </div>

      <div className="mt-3 flex items-center gap-1.5">
        {Array.from({ length: LOSS_THRESHOLD }).map((_, i) => (
          <span
            key={i}
            className={`h-1.5 flex-1 rounded-full ${
              i < data.consecutiveLosses ? "bg-negative" : "bg-surfaceAlt"
            }`}
          />
        ))}
      </div>
      <div className="mt-1.5 text-[11px] text-muted">
        {data.consecutiveLosses} / {LOSS_THRESHOLD} consecutive losses
      </div>

      {isPaused && (
        <div className="mt-3 rounded-lg bg-negative/10 p-2.5 text-xs text-negative">
          New entries paused — resumes in{" "}
          <span className="font-bold tabular-nums">{fmtCountdown(data.throttlePausedUntil - now)}</span>
        </div>
      )}

      {isReducedSize && (
        <div className="mt-3 rounded-lg bg-yellow-500/10 p-2.5 text-xs text-yellow-400">
          Trading resumed at 50% size for{" "}
          <span className="font-bold tabular-nums">{data.reducedSizeTradesRemaining}</span> more trade
          {data.reducedSizeTradesRemaining === 1 ? "" : "s"}
        </div>
      )}
    </div>
  );
}
