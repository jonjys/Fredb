"use client";

import { useState } from "react";
import { FuturesStatusResponse } from "@/lib/types";

export default function FuturesStatusBar({
  status,
  onChanged,
}: {
  status: FuturesStatusResponse | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);

  async function call(path: string) {
    setBusy(true);
    try {
      await fetch(path, { method: "POST" });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  const modeColors: Record<string, string> = {
    paper: "bg-accent/20 text-accent border-accent/40",
    testnet: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
    live: "bg-negative/20 text-negative border-negative/40",
  };

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-negative/40 bg-negative/10 p-3 text-sm text-negative">
        Leveraged futures trading can liquidate a position rapidly on a fast price move. Start in
        paper mode, keep leverage low, and only promote to testnet/live once you trust the
        behavior.
      </div>
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${
              modeColors[status?.mode ?? "paper"]
            }`}
          >
            {status?.mode ?? "—"} mode
          </span>
          <span className="text-sm text-muted">
            {status?.exchange ?? "—"} · {status?.symbols.join(", ") ?? "—"}
          </span>
          <span className="rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-xs font-semibold text-accent">
            {status?.leverage_default ?? "—"}x default leverage
          </span>
          {status?.kill_switch && (
            <span className="rounded-full border border-negative/40 bg-negative/20 px-3 py-1 text-xs font-semibold text-negative">
              KILL SWITCH ACTIVE: {status.kill_switch_reason}
            </span>
          )}
          {!status?.kill_switch && (
            <span
              className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                status?.running
                  ? "border-positive/40 bg-positive/20 text-positive"
                  : "border-border bg-surfaceAlt text-muted"
              }`}
            >
              {status?.running ? "RUNNING" : "STOPPED"}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {status?.kill_switch ? (
            <button
              disabled={busy}
              onClick={() => call("/api/futures/bot/kill-reset")}
              className="rounded-lg bg-yellow-600 px-4 py-2 text-sm font-semibold text-white hover:bg-yellow-500 disabled:opacity-50"
            >
              Reset kill switch
            </button>
          ) : status?.running ? (
            <button
              disabled={busy}
              onClick={() => call("/api/futures/bot/stop")}
              className="rounded-lg bg-surfaceAlt px-4 py-2 text-sm font-semibold text-white hover:bg-border disabled:opacity-50"
            >
              Stop
            </button>
          ) : (
            <button
              disabled={busy}
              onClick={() => call("/api/futures/bot/start")}
              className="rounded-lg bg-positive px-4 py-2 text-sm font-semibold text-black hover:bg-green-400 disabled:opacity-50"
            >
              Start
            </button>
          )}

          {confirmKill ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-negative">Close all positions now?</span>
              <button
                disabled={busy}
                onClick={() => {
                  call("/api/futures/bot/kill");
                  setConfirmKill(false);
                }}
                className="rounded-lg bg-negative px-3 py-2 text-xs font-semibold text-white hover:bg-red-500"
              >
                Confirm kill
              </button>
              <button
                onClick={() => setConfirmKill(false)}
                className="rounded-lg border border-border px-3 py-2 text-xs text-muted hover:bg-surfaceAlt"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              disabled={busy}
              onClick={() => setConfirmKill(true)}
              className="rounded-lg border border-negative/40 px-4 py-2 text-sm font-semibold text-negative hover:bg-negative/10 disabled:opacity-50"
            >
              Emergency Kill
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
