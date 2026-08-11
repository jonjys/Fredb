"use client";

import { useState } from "react";
import MarketTypeTabs, { MarketType } from "@/components/MarketTypeTabs";
import SpotDashboard from "@/components/SpotDashboard";
import FuturesDashboard from "@/components/FuturesDashboard";
import BottomNav from "@/components/BottomNav";
import { DashboardViewProvider } from "@/components/DashboardViewContext";

export default function DashboardPage() {
  const [market, setMarket] = useState<MarketType>("spot");

  return (
    <DashboardViewProvider>
      <main className="mx-auto max-w-7xl space-y-6 p-6">
        <header className="flex items-center justify-between">
          <h1 className="text-xl font-bold">Trading Bot Dashboard</h1>
        </header>

        <MarketTypeTabs active={market} onChange={setMarket} />

        {market === "spot" ? <SpotDashboard /> : <FuturesDashboard />}
      </main>
      <BottomNav />
    </DashboardViewProvider>
  );
}
