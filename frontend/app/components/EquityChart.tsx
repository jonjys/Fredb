"use client";

import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EquityPointOut } from "@/lib/types";
import { fmtTime } from "@/lib/format";

export default function EquityChart({ points }: { points: EquityPointOut[] | null }) {
  const data = (points ?? []).map((p) => ({
    time: fmtTime(p.timestamp),
    equity: Number(p.equity.toFixed(2)),
  }));

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2 text-xs uppercase tracking-wide text-muted">Equity curve</div>
      <div className="h-56 w-full">
        {data.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <XAxis dataKey="time" hide />
              <YAxis domain={["auto", "auto"]} hide />
              <Tooltip
                contentStyle={{ background: "#121820", border: "1px solid #243040", borderRadius: 8 }}
                labelStyle={{ color: "#8493a8" }}
              />
              <Line type="monotone" dataKey="equity" stroke="#3b82f6" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted">
            Not enough data yet
          </div>
        )}
      </div>
    </div>
  );
}
