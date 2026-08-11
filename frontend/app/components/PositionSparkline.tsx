"use client";

import { usePoll } from "@/lib/usePoll";
import { CandlePoint } from "@/lib/types";

/**
 * Recent price action for one open position, with entry/stop/target drawn
 * as reference lines — "is this thing about to hit my stop or my target"
 * at a glance, instead of doing the mental math from raw numbers.
 */
export default function PositionSparkline({
  candlesPath,
  entryPrice,
  stopLossPrice,
  takeProfitPrice,
  side,
  height = 48,
}: {
  candlesPath: string;
  entryPrice: number;
  stopLossPrice: number;
  takeProfitPrice: number;
  side: string;
  height?: number;
}) {
  const { data: candles } = usePoll<CandlePoint[]>(candlesPath, 5000);

  const closes = (candles ?? []).map((c) => c.close);
  if (closes.length < 2) {
    return (
      <div className="flex items-center text-[10px] text-muted" style={{ height }}>
        loading chart…
      </div>
    );
  }

  const values = [...closes, entryPrice, stopLossPrice, takeProfitPrice];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 200;

  const toY = (v: number) => height - ((v - min) / span) * height;
  const toX = (i: number) => (i / (closes.length - 1)) * width;

  const points = closes.map((c, i) => `${toX(i)},${toY(c)}`).join(" ");
  const last = closes[closes.length - 1];
  const inProfit = side === "short" ? last < entryPrice : last > entryPrice;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="h-12 w-full"
      role="img"
      aria-label="Recent price vs entry, stop, and target"
    >
      <line x1={0} x2={width} y1={toY(entryPrice)} y2={toY(entryPrice)} stroke="#8493a8" strokeWidth={1} strokeDasharray="2,3" />
      <line x1={0} x2={width} y1={toY(stopLossPrice)} y2={toY(stopLossPrice)} stroke="#ef4444" strokeWidth={1} strokeDasharray="2,3" />
      <line x1={0} x2={width} y1={toY(takeProfitPrice)} y2={toY(takeProfitPrice)} stroke="#22c55e" strokeWidth={1} strokeDasharray="2,3" />
      <polyline points={points} fill="none" stroke={inProfit ? "#22c55e" : "#ef4444"} strokeWidth={1.75} />
      <circle cx={toX(closes.length - 1)} cy={toY(last)} r={2.5} fill={inProfit ? "#22c55e" : "#ef4444"} />
    </svg>
  );
}
