"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Polls a same-origin API route on an interval. Using polling (instead of a
 * WebSocket straight to the browser) keeps the dashboard simple to deploy on
 * Vercel — no persistent connection infra needed, and it degrades gracefully
 * on flaky connections.
 */
export function usePoll<T>(url: string, intervalMs = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchOnce = useCallback(async () => {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json = (await res.json()) as T;
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "fetch failed");
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    fetchOnce();
    timer.current = setInterval(fetchOnce, intervalMs);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [fetchOnce, intervalMs]);

  return { data, error, loading, refetch: fetchOnce };
}
