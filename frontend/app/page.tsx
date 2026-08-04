"use client";

import { usePoll } from "@/lib/usePoll";
import {
  EquityPointOut,
  LogEntryOut,
  PositionOut,
  StatusResponse,
  TradeOut,
} from "@/lib/types";
import StatusBar from "@/components/StatusBar";
import BalanceCard from "@/components/BalanceCard";
import EquityChart from "@/components/EquityChart";
import PositionsTable from "@/components/PositionsTable";
import TradeHistory from "@/components/TradeHistory";
import LiveLog from "@/components/LiveLog";
import SettingsPanel from "@/components/SettingsPanel";

export default function DashboardPage() {
  const { data: status, error: statusError, refetch } = usePoll<StatusResponse>(
    "/api/status",
    3000
  );
  const { data: positions } = usePoll<PositionOut[]>("/api/positions", 3000);
  const { data: trades } = usePoll<TradeOut[]>("/api/trades", 8000);
  const { data: logs } = usePoll<LogEntryOut[]>("/api/logs", 4000);
  const { data: equity } = usePoll<EquityPointOut[]>("/api/equity", 10000);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Trading Bot Dashboard</h1>
        {statusError && (
          <span className="text-sm text-negative">Backend unreachable: {statusError}</span>
        )}
      </header>

      <StatusBar status={status} onChanged={refetch} />
      <BalanceCard status={status} />
      <EquityChart points={equity} />
      <PositionsTable positions={positions} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <TradeHistory trades={trades} />
        <LiveLog logs={logs} />
      </div>
      <SettingsPanel />
    </main>
  );
}
