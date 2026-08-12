// app/lib/types.ts
export interface StatusResponse {
  mode: string;
  exchange: string;
  symbols: string[];
  running: boolean;
  kill_switch: boolean;
  kill_switch_reason: string;
  equity: number;
  quote_balance: number;
  daily_start_equity: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  open_positions_count: number;
  max_concurrent_positions: number;
  throttle_paused_until: number;
  consecutive_losses: number;
  reduced_size_trades_remaining: number;
}

export interface PositionOut {
  id: number;
  symbol: string;
  side: string;
  status: string;
  entry_price: number;
  qty: number;
  stop_loss_price: number;
  take_profit_price: number;
  trailing_active: boolean;
  trailing_high: number;
  current_price: number | null;
  unrealized_pnl_quote: number | null;
  unrealized_pnl_pct: number | null;
  opened_at: number;
}

export interface TradeOut {
  id: number;
  symbol: string;
  side: string;
  status: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl_quote: number;
  pnl_pct: number;
  close_reason: string;
  opened_at: number;
  closed_at: number;
}

export interface LogEntryOut {
  timestamp: number;
  level: string;
  message: string;
}

export interface SettingsOut {
  max_risk_per_trade_pct: number;
  max_concurrent_positions: number;
  take_profit_pct: number;
  trailing_stop_pct: number;
  stop_loss_pct: number;
  atr_multiplier: number;
  max_daily_loss_pct: number;
  taker_fee_pct: number;
  slippage_buffer_pct: number;
  poll_interval_seconds: number;
}

export interface EquityPointOut {
  timestamp: number;
  equity: number;
  realized_pnl_today: number;
}

export interface PerformanceStatsOut {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  net_pnl_quote: number;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number | null;
  avg_win_quote: number;
  avg_loss_quote: number;
  best_trade_quote: number;
  worst_trade_quote: number;
  current_streak: number;
  best_win_streak: number;
  long_trades: number;
  short_trades: number;
  long_win_rate_pct: number | null;
  short_win_rate_pct: number | null;
}

// ---- Futures ----------------------------------------------------------

export interface FuturesStatusResponse {
  enabled: boolean;
  mode: string;
  exchange: string;
  symbols: string[];
  running: boolean;
  kill_switch: boolean;
  kill_switch_reason: string;
  equity: number;
  quote_balance: number;
  daily_start_equity: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  open_positions_count: number;
  max_concurrent_positions: number;
  leverage_default: number;
  leverage_mode: string;
  max_leverage: number;
  auto_leverage_min: number;
  auto_leverage_max: number;
  throttle_paused_until: number;
  consecutive_losses: number;
  reduced_size_trades_remaining: number;
}

export interface FuturesPositionOut {
  id: number;
  symbol: string;
  side: string;
  status: string;
  leverage: number;
  entry_price: number;
  qty: number;
  margin_used: number;
  liquidation_price: number;
  stop_loss_price: number;
  take_profit_price: number;
  trailing_active: boolean;
  trailing_high: number;
  current_price: number | null;
  unrealized_pnl_quote: number | null;
  unrealized_pnl_pct: number | null;
  opened_at: number;
}

export interface CandlePoint {
  timestamp: number;
  close: number;
}

export interface OhlcvBar {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OrderBookData {
  symbol: string;
  bids: [number, number][]; // [price, qty], best-first
  asks: [number, number][];
}

export interface FuturesTradeOut {
  id: number;
  symbol: string;
  side: string;
  status: string;
  leverage: number;
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl_quote: number;
  pnl_pct: number;
  close_reason: string;
  opened_at: number;
  closed_at: number;
}
