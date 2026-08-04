"use client";

import { useEffect, useState } from "react";
import { SettingsOut } from "@/lib/types";

const FIELDS: Array<{ key: keyof SettingsOut; label: string; step: string; hint: string }> = [
  { key: "max_risk_per_trade_pct", label: "Max risk per trade (%)", step: "0.1", hint: "% of equity risked per trade" },
  { key: "max_concurrent_positions", label: "Max concurrent positions", step: "1", hint: "How many trades can be open at once" },
  { key: "take_profit_pct", label: "Take profit (%)", step: "0.05", hint: "Target gain before trailing-stop activates" },
  { key: "trailing_stop_pct", label: "Trailing stop (%)", step: "0.05", hint: "Distance kept below the peak once trailing" },
  { key: "stop_loss_pct", label: "Stop loss floor (%)", step: "0.05", hint: "Minimum hard-stop distance from entry" },
  { key: "atr_multiplier", label: "ATR multiplier", step: "0.1", hint: "Volatility multiplier for stop distance" },
  { key: "max_daily_loss_pct", label: "Max daily loss (%)", step: "0.5", hint: "Kill switch triggers past this drawdown" },
  { key: "taker_fee_pct", label: "Taker fee (%)", step: "0.01", hint: "Exchange fee assumption" },
  { key: "slippage_buffer_pct", label: "Slippage buffer (%)", step: "0.01", hint: "Expected slippage per fill" },
  { key: "poll_interval_seconds", label: "Poll interval (s)", step: "1", hint: "How often the strategy loop runs" },
];

export default function SettingsPanel() {
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [draft, setDraft] = useState<Partial<SettingsOut>>({});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((s: SettingsOut) => {
        setSettings(s);
        setDraft(s);
      });
  }, []);

  async function save() {
    setSaving(true);
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      const updated = await res.json();
      setSettings(updated);
      setDraft(updated);
      setSavedAt(Date.now());
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-xs uppercase tracking-wide text-muted"
      >
        <span>Risk settings</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="mt-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FIELDS.map((f) => (
              <label key={f.key} className="flex flex-col gap-1">
                <span className="text-sm text-white/90">{f.label}</span>
                <input
                  type="number"
                  step={f.step}
                  value={draft[f.key] ?? ""}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, [f.key]: parseFloat(e.target.value) }))
                  }
                  className="rounded-lg border border-border bg-surfaceAlt px-3 py-2 text-sm text-white outline-none focus:border-accent"
                />
                <span className="text-xs text-muted">{f.hint}</span>
              </label>
            ))}
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={save}
              disabled={saving || !settings}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save settings"}
            </button>
            {savedAt && Date.now() - savedAt < 4000 && (
              <span className="text-sm text-positive">Saved</span>
            )}
          </div>
          <p className="mt-2 text-xs text-muted">
            Changes apply immediately to the running bot. They are not (yet) written back to the
            backend&apos;s .env file, so a redeploy resets them to the environment defaults.
          </p>
        </div>
      )}
    </div>
  );
}
