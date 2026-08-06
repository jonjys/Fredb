"use client";

export type MarketType = "spot" | "futures";

export default function MarketTypeTabs({
  active,
  onChange,
}: {
  active: MarketType;
  onChange: (m: MarketType) => void;
}) {
  const tabs: { key: MarketType; label: string }[] = [
    { key: "spot", label: "Spot" },
    { key: "futures", label: "Futures (leverage)" },
  ];

  return (
    <div className="flex gap-2 rounded-xl border border-border bg-surface p-1">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold transition ${
            active === t.key
              ? "bg-accent text-white"
              : "text-muted hover:bg-surfaceAlt hover:text-white"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
