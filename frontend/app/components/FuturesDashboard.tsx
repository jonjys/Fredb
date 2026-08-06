"use client";

import { usePoll } from "@/lib/usePoll";
import {
  EquityPointOut,
  FuturesPositionOut,
  FuturesStatusResponse,
  FuturesTradeOut,
  LogEntryOut,
} from "@/lib/types";
import FuturesStatusBar from "@/components/FuturesStatusBar";
import FuturesBalanceCard from "@/components/FuturesBalanceCard";
import EquityChart from "@/components/EquityChart";
import FuturesPositionsTable from "@/components/FuturesPositionsTable";
import FuturesTradeHistory from "@/components/FuturesTradeHistory";
import LiveLog from "@/components/LiveLog";
import LeverageSelector from "@/components/LeverageSelector";

export default function FuturesDashboard() {
  const { data: status, error: statusError, refetch } = usePoll<FuturesStatusResponse>(
    "/api/futures/status",
    3000
  );
  const { data: positions } = usePoll<FuturesPositionOut[]>("/api/futures/positions", 3000);
  const { data: trades } = usePoll<FuturesTradeOut[]>("/api/futures/trades", 8000);
  const { data: logs } = usePoll<LogEntryOut[]>("/api/futures/logs", 4000);
  const { data: equity } = usePoll<EquityPointOut[]>("/api/futures/equity", 10000);

  async function changeLeverage(leverage: number) {
    await fetch("/api/futures/leverage", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leverage }),
    });
    refetch();
  }

  async function setAutoLeverage() {
    await fetch("/api/futures/leverage", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "auto" }),
    });
    refetch();
  }

  if (statusError && statusError.startsWith("503")) {
    return (
      <div className="rounded-xl border border-border bg-surface p-6 text-center text-muted">
        Futures trading is not enabled on this backend. Set{" "}
        <code className="rounded bg-surfaceAlt px-1.5 py-0.5 text-white">FUTURES_ENABLED=true</code>{" "}
        in the backend environment to turn it on.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {statusError && (
        <div className="rounded-lg border border-negative/40 bg-negative/10 p-3 text-sm text-negative">
          Backend unreachable: {statusError}
        </div>
      )}
      <FuturesStatusBar status={status} onChanged={refetch} />
      <FuturesBalanceCard status={status} />
      <LeverageSelector
        current={status?.leverage_default ?? 8}
        mode={status?.leverage_mode ?? "auto"}
        autoMin={status?.auto_leverage_min ?? 5}
        autoMax={status?.auto_leverage_max ?? 10}
        maxLeverage={status?.max_leverage ?? 50}
        onChangeLeverage={changeLeverage}
        onSetAuto={setAutoLeverage}
      />
      <EquityChart points={equity} />
      <FuturesPositionsTable positions={positions} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <FuturesTradeHistory trades={trades} />
        <LiveLog logs={logs} />
      </div>
    </div>
  );
}
