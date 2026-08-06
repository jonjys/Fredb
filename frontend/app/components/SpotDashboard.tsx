"use client";

import { usePoll } from "@/lib/usePoll";
import {
  EquityPointOut,
  LogEntryOut,
  PerformanceStatsOut,
  PositionOut,
  StatusResponse,
  TradeOut,
} from "@/lib/types";
import PerformancePanel from "@/components/PerformancePanel";
import StatusBar from "@/components/StatusBar";
import BalanceCard from "@/components/BalanceCard";
import EquityChart from "@/components/EquityChart";
import PositionsTable from "@/components/PositionsTable";
import TradeHistory from "@/components/TradeHistory";
import LiveLog from "@/components/LiveLog";
import SettingsPanel from "@/components/SettingsPanel";

export default function SpotDashboard() {
  const { data: status, error: statusError, refetch } = usePoll<StatusResponse>(
    "/api/status",
    3000
  );
  const { data: positions } = usePoll<PositionOut[]>("/api/positions", 3000);
  const { data: trades } = usePoll<TradeOut[]>("/api/trades", 8000);
  const { data: logs } = usePoll<LogEntryOut[]>("/api/logs", 4000);
  const { data: equity } = usePoll<EquityPointOut[]>("/api/equity", 10000);
  const { data: stats } = usePoll<PerformanceStatsOut>("/api/stats", 8000);

  return (
    <div className="space-y-6">
      {statusError && (
        <div className="rounded-lg border border-negative/40 bg-negative/10 p-3 text-sm text-negative">
          Backend unreachable: {statusError}
        </div>
      )}
      <StatusBar status={status} onChanged={refetch} />
      <BalanceCard status={status} />
      <PerformancePanel stats={stats} />
      <EquityChart points={equity} />
      <PositionsTable positions={positions} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <TradeHistory trades={trades} />
        <LiveLog logs={logs} />
      </div>
      <SettingsPanel />
    </div>
  );
}
