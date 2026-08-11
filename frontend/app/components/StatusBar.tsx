"use client";

import { useState } from "react";
import { StatusResponse } from "@/lib/types";
import ResetButton from "@/components/ResetButton";

export default function StatusBar({
  status,
  onChanged,
}: {
  status: StatusResponse | null;
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
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface p-3 md:gap-4 md:p-4">
      <div className="flex flex-wrap items-center gap-2 md:gap-3">
        <span
          className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${
            modeColors[status?.mode ?? "paper"]
          }`}
        >
          {status?.mode ?? "—"} mode
        </span>
        <span className="hidden text-sm text-muted sm:inline">
          {status?.exchange ?? "—"} · {status?.symbols.join(", ") ?? "—"}
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

      <div className="flex flex-wrap items-center gap-2">
        {status?.kill_switch ? (
          <button
            disabled={busy}
            onClick={() => call("/api/bot/kill-reset")}
            className="rounded-lg bg-yellow-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-yellow-500 disabled:opacity-50 md:px-4 md:py-2 md:text-sm"
          >
            Reset kill switch
          </button>
        ) : status?.running ? (
          <button
            disabled={busy}
            onClick={() => call("/api/bot/stop")}
            className="rounded-lg bg-surfaceAlt px-3 py-1.5 text-xs font-semibold text-white hover:bg-border disabled:opacity-50 md:px-4 md:py-2 md:text-sm"
          >
            Stop
          </button>
        ) : (
          <button
            disabled={busy}
            onClick={() => call("/api/bot/start")}
            className="rounded-lg bg-positive px-3 py-1.5 text-xs font-semibold text-black hover:bg-green-400 disabled:opacity-50 md:px-4 md:py-2 md:text-sm"
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
                call("/api/bot/kill");
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
            className="rounded-lg border border-negative/40 px-3 py-1.5 text-xs font-semibold text-negative hover:bg-negative/10 disabled:opacity-50 md:px-4 md:py-2 md:text-sm"
          >
            Emergency Kill
          </button>
        )}
        {status?.mode === "paper" && <ResetButton resetPath="/api/bot/reset" />}
      </div>
    </div>
  );
}
