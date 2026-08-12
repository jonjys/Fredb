// app/components/FuturesDashboard.tsx
"use client";

import { usePoll } from "@/lib/usePoll";
import {
  EquityPointOut,
  FuturesPositionOut,
  FuturesStatusResponse,
  FuturesTradeOut,
  LogEntryOut,
  PerformanceStatsOut,
} from "@/lib/types";
import PerformancePanel from "@/components/PerformancePanel";
import PerformanceGrid from "@/components/PerformanceGrid";
import FuturesStatusBar from "@/components/FuturesStatusBar";
import FuturesBalanceCard from "@/components/FuturesBalanceCard";
import EquityChart from "@/components/EquityChart";
import FuturesPositionsTable from "@/components/FuturesPositionsTable";
import MobilePositionCard from "@/components/MobilePositionCard";
import MarketPanel from "@/components/MarketPanel";
import LiveOrdersPanel, { LiveOrderRowData } from "@/components/LiveOrdersPanel";
import FuturesTradeHistory from "@/components/FuturesTradeHistory";
import LiveLog from "@/components/LiveLog";
import LeverageSelector from "@/components/LeverageSelector";
import CircuitBreakerStatus from "@/components/CircuitBreakerStatus";
import { MobileSection } from "@/components/DashboardViewContext";

export default function FuturesDashboard() {
  const { data: status, error: statusError, refetch } = usePoll<FuturesStatusResponse>(
    "/api/futures/status",
    3000
  );
  const { data: positions } = usePoll<FuturesPositionOut[]>("/api/futures/positions", 3000);
  const { data: trades } = usePoll<FuturesTradeOut[]>("/api/futures/trades", 8000);
  const { data: logs } = usePoll<LogEntryOut[]>("/api/futures/logs", 4000);
  const { data: equity } = usePoll<EquityPointOut[]>("/api/futures/equity", 10000);
  const { data: stats } = usePoll<PerformanceStatsOut>("/api/futures/stats", 8000);

  async function changeLeverage(leverage: number) {
    await fetch("/api/futures/leverage", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leverage }),
    });
    refetch();
  }

  const liveOrders: LiveOrderRowData[] = (positions ?? []).map((p) => ({
    id: p.id,
    symbol: p.symbol,
    side: p.side,
    leverage: p.leverage,
    entryPrice: p.entry_price,
    currentPrice: p.current_price,
    stopLossPrice: p.stop_loss_price,
    takeProfitPrice: p.take_profit_price,
    unrealizedPnlQuote: p.unrealized_pnl_quote,
    unrealizedPnlPct: p.unrealized_pnl_pct,
    openedAt: p.opened_at,
    candlesPath: `/api/futures/positions/${p.id}/candles`,
  }));

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

  const marginUsed = (positions ?? []).reduce((sum, p) => sum + p.margin_used, 0);
  const throttlePaused = (status?.throttle_paused_until ?? 0) > Date.now() / 1000;

  return (
    <div className="space-y-3 pb-20 md:space-y-6 md:pb-0">
      {statusError && (
        <div className="rounded-lg border border-negative/40 bg-negative/10 p-3 text-sm text-negative">
          Backend unreachable: {statusError}
        </div>
      )}

      <MobileSection view="dashboard">
        <div className="space-y-3 md:space-y-6">
          <PerformanceGrid
            data={{
              winRatePct: stats && stats.total_trades > 0 ? stats.win_rate_pct : null,
              netPnlQuote: stats && stats.total_trades > 0 ? stats.net_pnl_quote : null,
              activePositionsLabel: `${status?.open_positions_count ?? 0} / ${status?.max_concurrent_positions ?? "—"} · $${marginUsed.toFixed(0)} margin`,
              running: status?.running ?? false,
              killSwitch: status?.kill_switch ?? false,
              killSwitchReason: status?.kill_switch_reason,
              throttlePaused,
            }}
          />
          <FuturesStatusBar status={status} onChanged={refetch} />
          <FuturesBalanceCard status={status} />
          <MarketPanel
            symbols={status?.symbols ?? []}
            ohlcvBasePath="/api/futures/market/ohlcv"
            orderBookBasePath="/api/futures/market/orderbook"
          />
          <PerformancePanel stats={stats} />
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
        </div>
      </MobileSection>

      <MobileSection view="positions">
        <div className="space-y-3 md:space-y-6">
          <LiveOrdersPanel orders={liveOrders} />
          <div className="space-y-3 md:hidden">
            {liveOrders.map((o) => (
              <MobilePositionCard key={o.id} position={o} />
            ))}
          </div>
          <div className="hidden md:block">
            <FuturesPositionsTable positions={positions} />
          </div>
          <div className="md:hidden">
            <FuturesTradeHistory trades={trades} />
          </div>
        </div>
      </MobileSection>

      <MobileSection view="logs">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <FuturesTradeHistory trades={trades} />
          <LiveLog logs={logs} />
        </div>
      </MobileSection>

      <MobileSection view="settings">
        <div className="space-y-3 md:space-y-6">
          <CircuitBreakerStatus
            data={{
              consecutiveLosses: status?.consecutive_losses ?? 0,
              throttlePausedUntil: status?.throttle_paused_until ?? 0,
              reducedSizeTradesRemaining: status?.reduced_size_trades_remaining ?? 0,
            }}
          />
          <div className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">
            Futures risk settings are configured server-side (see backend/.env) — the leverage
            control above is the one live-adjustable setting exposed here.
          </div>
        </div>
      </MobileSection>
    </div>
  );
}
