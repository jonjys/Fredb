"use client";

import { createContext, useContext, useState, ReactNode } from "react";

export type DashboardView = "dashboard" | "positions" | "settings" | "logs";

const DashboardViewCtx = createContext<{
  view: DashboardView;
  setView: (v: DashboardView) => void;
} | null>(null);

export function DashboardViewProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<DashboardView>("dashboard");
  return <DashboardViewCtx.Provider value={{ view, setView }}>{children}</DashboardViewCtx.Provider>;
}

export function useDashboardView() {
  const ctx = useContext(DashboardViewCtx);
  if (!ctx) throw new Error("useDashboardView must be used within a DashboardViewProvider");
  return ctx;
}

/** Shows children on desktop always; on mobile (<md) only while `view` is
 * the section this content belongs to — the bottom nav below md is what
 * makes each screen "one job" instead of one long stacked scroll. */
export function MobileSection({ view, children }: { view: DashboardView; children: ReactNode }) {
  const { view: active } = useDashboardView();
  return <div className={active === view ? "block" : "hidden md:block"}>{children}</div>;
}
