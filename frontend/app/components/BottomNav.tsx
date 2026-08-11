"use client";

import { DashboardView, useDashboardView } from "@/components/DashboardViewContext";

const TABS: { view: DashboardView; label: string; icon: string }[] = [
  { view: "dashboard", label: "Dashboard", icon: "M4 13h6V4H4v9zm0 7h6v-5H4v5zm10 0h6V11h-6v9zm0-16v5h6V4h-6z" },
  { view: "positions", label: "Positions", icon: "M3 3v18h18M7 15l4-5 3 3 5-7" },
  { view: "settings", label: "Settings", icon: "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" },
  { view: "logs", label: "Logs", icon: "M4 6h16M4 12h16M4 18h10" },
];

/** Mobile-only (md:hidden) sticky tab bar. Desktop already shows every
 * section stacked at once, so this exists purely to give mobile one
 * focused screen at a time instead of one very long scroll. */
export default function BottomNav() {
  const { view, setView } = useDashboardView();

  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-surface/95 backdrop-blur md:hidden">
      <div className="grid grid-cols-4">
        {TABS.map((tab) => {
          const active = view === tab.view;
          return (
            <button
              key={tab.view}
              onClick={() => setView(tab.view)}
              className={`flex flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition-colors ${
                active ? "text-accent" : "text-muted"
              }`}
              aria-current={active ? "page" : undefined}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5">
                <path d={tab.icon} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {tab.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
