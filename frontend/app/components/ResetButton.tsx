"use client";

import { useState } from "react";

/**
 * Wipes every position/trade/equity point and restarts the paper wallet at
 * $1000, as if the bot had never run — for quickly judging a strategy
 * change without old losing trades muddying the stats. Paper mode only;
 * the backend refuses this in testnet/live (see /api/bot/reset).
 */
export default function ResetButton({ resetPath }: { resetPath: string }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function doReset() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(resetPath, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || body.error || `${res.status} ${res.statusText}`);
      }
      // Hard reload rather than refetching individual panels — every poller
      // on the page (equity, positions, trades, stats) needs to forget its
      // old data at once, and a full reload is the simplest way to
      // guarantee nothing stale survives the reset.
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "reset failed");
      setBusy(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-negative">Wipe all history and restart at $1000?</span>
        <button
          disabled={busy}
          onClick={doReset}
          className="rounded-lg bg-negative px-3 py-2 text-xs font-semibold text-white hover:bg-red-500 disabled:opacity-50"
        >
          {busy ? "Resetting…" : "Confirm reset"}
        </button>
        <button
          disabled={busy}
          onClick={() => setConfirming(false)}
          className="rounded-lg border border-border px-3 py-2 text-xs text-muted hover:bg-surfaceAlt"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => setConfirming(true)}
        className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-muted hover:border-negative/40 hover:text-negative"
        title="Wipe all paper trading history and restart at $1000"
      >
        Reset to $1000
      </button>
      {error && <span className="text-xs text-negative">{error}</span>}
    </div>
  );
}
