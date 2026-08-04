import { LogEntryOut } from "@/lib/types";
import { fmtTime } from "@/lib/format";

const levelColors: Record<string, string> = {
  INFO: "text-muted",
  WARNING: "text-yellow-400",
  ERROR: "text-negative",
  CRITICAL: "text-negative",
};

export default function LiveLog({ logs }: { logs: LogEntryOut[] | null }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 text-xs uppercase tracking-wide text-muted">Live log</div>
      <div className="h-64 overflow-y-auto rounded-lg bg-black/40 p-3 font-mono text-xs">
        {(logs ?? []).length === 0 && <div className="text-muted">No log entries yet</div>}
        {[...(logs ?? [])].reverse().map((l, i) => (
          <div key={i} className="mb-1">
            <span className="text-muted">{fmtTime(l.timestamp)}</span>{" "}
            <span className={levelColors[l.level] ?? "text-white"}>[{l.level}]</span>{" "}
            <span className="text-white/90">{l.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
