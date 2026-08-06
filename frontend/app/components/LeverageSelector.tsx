"use client";

import { useState } from "react";

const LEVERAGE_OPTIONS = [2, 3, 5, 10, 15, 20, 25, 50];
const HIGH_LEVERAGE_THRESHOLD = 10;

export default function LeverageSelector({
  current,
  mode,
  autoMin,
  autoMax,
  maxLeverage,
  onChangeLeverage,
  onSetAuto,
}: {
  current: number;
  mode: string;
  autoMin: number;
  autoMax: number;
  maxLeverage: number;
  onChangeLeverage: (leverage: number) => void;
  onSetAuto: () => void;
}) {
  const [pending, setPending] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  const options = LEVERAGE_OPTIONS.filter((l) => l <= maxLeverage);
  const isAuto = mode === "auto";

  async function apply(leverage: number) {
    setSaving(true);
    try {
      await onChangeLeverage(leverage);
    } finally {
      setSaving(false);
      setPending(null);
    }
  }

  function select(leverage: number) {
    if (leverage >= HIGH_LEVERAGE_THRESHOLD && (isAuto || leverage !== current)) {
      setPending(leverage);
      return;
    }
    apply(leverage);
  }

  async function enableAuto() {
    setSaving(true);
    try {
      await onSetAuto();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-muted">Leverage</span>
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-0.5">
          <button
            disabled={saving}
            onClick={enableAuto}
            className={`rounded px-3 py-1 text-xs font-semibold disabled:opacity-50 ${
              isAuto ? "bg-accent text-white" : "text-muted hover:text-white"
            }`}
          >
            Auto
          </button>
          <button
            disabled={saving}
            onClick={() => isAuto && apply(current)}
            className={`rounded px-3 py-1 text-xs font-semibold disabled:opacity-50 ${
              !isAuto ? "bg-accent text-white" : "text-muted hover:text-white"
            }`}
          >
            Manual
          </button>
        </div>
      </div>

      {isAuto ? (
        <p className="text-sm text-white">
          Bot picks up to <span className="font-semibold text-accent">{current}x</span> automatically
          (adapts within {autoMin}x–{autoMax}x based on recent BTC volatility, recomputed every 5
          minutes).
        </p>
      ) : (
        <p className="text-sm text-white">
          Fixed ceiling: <span className="font-semibold text-accent">{current}x</span>
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {options.map((lev) => (
          <button
            key={lev}
            disabled={saving}
            onClick={() => select(lev)}
            className={`rounded-lg border px-3 py-2 text-sm font-semibold disabled:opacity-50 ${
              !isAuto && current === lev
                ? "border-accent bg-accent/20 text-accent"
                : "border-border bg-surfaceAlt text-white hover:border-accent/50"
            }`}
          >
            {lev}x
          </button>
        ))}
      </div>

      {pending !== null && (
        <div className="mt-3 rounded-lg border border-negative/40 bg-negative/10 p-3 text-sm">
          <p className="text-negative">
            {pending}x leverage means roughly a {(100 / pending).toFixed(1)}% adverse price move
            liquidates the position. Confirm you understand the risk.
          </p>
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => apply(pending)}
              className="rounded-lg bg-negative px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-500"
            >
              Confirm {pending}x
            </button>
            <button
              onClick={() => setPending(null)}
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted hover:bg-surfaceAlt"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      <p className="mt-2 text-xs text-muted">
        Risk per trade stays capped at the configured % of equity regardless of leverage — higher
        leverage only frees up margin, it does not increase the dollar risk on a single trade. The
        bot also automatically caps effective leverage below whatever level would put the stop-loss
        past the exchange&apos;s liquidation price, in both Auto and Manual mode.
      </p>
    </div>
  );
}
