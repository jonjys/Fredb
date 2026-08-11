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
import PerformanceGrid from "@/components/PerformanceGrid";
import StatusBar from "@/components/StatusBar";
import BalanceCard from "@/components/BalanceCard";
import EquityChart from "@/components/EquityChart";
import PositionsTable from "@/components/PositionsTable";
import MobilePositionCard from "@/components/MobilePositionCard";
import MarketPanel from "@/components/MarketPanel";
import LiveOrdersPanel, { LiveOrderRowData } from "@/components/LiveOrdersPanel";
import TradeHistory from "@/components/TradeHistory";
import LiveLog from "@/components/LiveLog";
import SettingsPanel from "@/components/SettingsPanel";
import { MobileSection } from "@/components/DashboardViewContext";

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

  const liveOrders: LiveOrderRowData[] = (positions ?? []).map((p) => ({
    id: p.id,
    symbol: p.symbol,
    side: p.side,
    entryPrice: p.entry_price,
    currentPrice: p.current_price,
    stopLossPrice: p.stop_loss_price,
    takeProfitPrice: p.take_profit_price,
    unrealizedPnlQuote: p.unrealized_pnl_quote,
    unrealizedPnlPct: p.unrealized_pnl_pct,
    openedAt: p.opened_at,
    candlesPath: `/api/positions/${p.id}/candles`,
  }));

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      {statusError && (
        <div className="rounded-lg border border-negative/40 bg-negative/10 p-3 text-sm text-negative">
          Backend unreachable: {statusError}
        </div>
      )}

      <MobileSection view="dashboard">
        <div className="space-y-6">
          <PerformanceGrid
            data={{
              winRatePct: stats && stats.total_trades > 0 ? stats.win_rate_pct : null,
              netPnlQuote: stats && stats.total_trades > 0 ? stats.net_pnl_quote : null,
              activePositionsLabel: `${status?.open_positions_count ?? 0} / ${status?.max_concurrent_positions ?? "—"}`,
              running: status?.running ?? false,
              killSwitch: status?.kill_switch ?? false,
              killSwitchReason: status?.kill_switch_reason,
              throttlePaused: (status?.throttle_paused_until ?? 0) > Date.now() / 1000,
            }}
          />
          <StatusBar status={status} onChanged={refetch} />
          <BalanceCard status={status} />
          <MarketPanel
            symbols={status?.symbols ?? []}
            ohlcvBasePath="/api/market/ohlcv"
            orderBookBasePath="/api/market/orderbook"
          />
          <PerformancePanel stats={stats} />
          <EquityChart points={equity} />
        </div>
      </MobileSection>

      <MobileSection view="positions">
        <div className="space-y-6">
          <LiveOrdersPanel orders={liveOrders} />
          <div className="space-y-3 md:hidden">
            {liveOrders.map((o) => (
              <MobilePositionCard key={o.id} position={o} />
            ))}
          </div>
          <div className="hidden md:block">
            <PositionsTable positions={positions} />
          </div>
        </div>
      </MobileSection>

      <MobileSection view="logs">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <TradeHistory trades={trades} />
          <LiveLog logs={logs} />
        </div>
      </MobileSection>

      <MobileSection view="settings">
        <SettingsPanel />
      </MobileSection>
    </div>
  );
}
