"use client";

import { usePoll } from "@/lib/usePoll";
import { OhlcvBar } from "@/lib/types";
import { fmtMoney } from "@/lib/format";

const POSITIVE = "#22c55e";
const NEGATIVE = "#ef4444";

/** Real OHLC candlesticks + a volume strip, built as plain SVG rather than
 * pulling in a charting library — the codebase already leans on hand-built
 * SVG for sparklines, and a candlestick is just wicks + rectangles, not
 * worth a new dependency for. */
export default function CandlestickChart({
  ohlcvPath,
  height = 260,
  pollMs = 5000,
}: {
  ohlcvPath: string;
  height?: number;
  pollMs?: number;
}) {
  const { data: bars } = usePoll<OhlcvBar[]>(ohlcvPath, pollMs);

  if (!bars || bars.length < 2) {
    return (
      <div className="flex items-center justify-center text-sm text-muted" style={{ height }}>
        Loading chart…
      </div>
    );
  }

  const width = 800;
  const volumeHeight = 36;
  const candleAreaHeight = height - volumeHeight - 8;

  const highs = bars.map((b) => b.high);
  const lows = bars.map((b) => b.low);
  const priceMax = Math.max(...highs);
  const priceMin = Math.min(...lows);
  const priceSpan = priceMax - priceMin || 1;
  const volMax = Math.max(...bars.map((b) => b.volume)) || 1;

  const n = bars.length;
  const slot = width / n;
  const bodyWidth = Math.max(1, slot * 0.62);

  const toY = (price: number) => candleAreaHeight - ((price - priceMin) / priceSpan) * candleAreaHeight;

  const last = bars[bars.length - 1];
  const lastY = toY(last.close);
  const lastUp = last.close >= last.open;

  // Evenly spaced price gridlines with labels, like a real trading chart's
  // right-hand axis.
  const gridLines = 4;
  const gridPrices = Array.from({ length: gridLines + 1 }, (_, i) => priceMin + (priceSpan * i) / gridLines);

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width + 70} ${height}`} width="100%" height={height} preserveAspectRatio="none">
        {/* grid + price labels */}
        {gridPrices.map((p, i) => (
          <g key={i}>
            <line x1={0} x2={width} y1={toY(p)} y2={toY(p)} stroke="#1B222C" strokeWidth={1} />
            <text x={width + 6} y={toY(p) + 3} fontSize="10" fill="#5B6577" fontFamily="ui-monospace, monospace">
              {fmtMoney(p, p < 10 ? 4 : 2)}
            </text>
          </g>
        ))}

        {/* last-price reference line */}
        <line
          x1={0} x2={width} y1={lastY} y2={lastY}
          stroke={lastUp ? POSITIVE : NEGATIVE} strokeWidth={1} strokeDasharray="4,3" opacity={0.7}
        />
        <text
          x={width + 6} y={lastY + 3} fontSize="10" fontWeight={700}
          fill={lastUp ? POSITIVE : NEGATIVE} fontFamily="ui-monospace, monospace"
        >
          {fmtMoney(last.close, last.close < 10 ? 4 : 2)}
        </text>

        {/* candles */}
        {bars.map((bar, i) => {
          const x = i * slot + slot / 2;
          const up = bar.close >= bar.open;
          const color = up ? POSITIVE : NEGATIVE;
          const bodyTop = toY(Math.max(bar.open, bar.close));
          const bodyBottom = toY(Math.min(bar.open, bar.close));
          const bodyH = Math.max(1, bodyBottom - bodyTop);
          return (
            <g key={bar.timestamp}>
              <line x1={x} x2={x} y1={toY(bar.high)} y2={toY(bar.low)} stroke={color} strokeWidth={1} />
              <rect x={x - bodyWidth / 2} y={bodyTop} width={bodyWidth} height={bodyH} fill={color} />
            </g>
          );
        })}

        {/* volume strip */}
        {bars.map((bar, i) => {
          const x = i * slot + slot / 2;
          const up = bar.close >= bar.open;
          const h = (bar.volume / volMax) * volumeHeight;
          return (
            <rect
              key={`v-${bar.timestamp}`}
              x={x - bodyWidth / 2}
              y={height - h}
              width={bodyWidth}
              height={h}
              fill={up ? POSITIVE : NEGATIVE}
              opacity={0.35}
            />
          );
        })}
      </svg>
    </div>
  );
}
