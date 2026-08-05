"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center">
        <h1 className="text-lg font-bold text-negative">Dashboard crashed</h1>
        <p className="mt-2 text-sm text-muted">
          Something went wrong rendering the dashboard. The trading bot itself keeps running on
          the backend regardless — this only affects this browser tab.
        </p>
        <p className="mt-2 break-all text-xs text-muted">{error.message}</p>
        <button
          onClick={reset}
          className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
