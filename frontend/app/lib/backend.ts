import { NextResponse } from "next/server";

/**
 * Server-only helper for talking to the trading bot backend.
 *
 * This file must never be imported from a Client Component — it reads
 * BACKEND_URL / DASHBOARD_API_TOKEN from process.env, which are NOT
 * prefixed with NEXT_PUBLIC_ and therefore only exist on the server.
 * Route handlers under app/api/** call this to proxy requests, so the
 * secret token never reaches the browser.
 */
export async function backendFetch(path: string, init?: RequestInit): Promise<Response> {
  const backendUrl = process.env.BACKEND_URL;
  const token = process.env.DASHBOARD_API_TOKEN;

  if (!backendUrl || !token) {
    throw new Error(
      "BACKEND_URL / DASHBOARD_API_TOKEN are not configured on the server environment"
    );
  }

  return fetch(`${backendUrl}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });
}

export async function proxyGet(path: string): Promise<NextResponse> {
  try {
    const res = await backendFetch(path);
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "backend unreachable" },
      { status: 502 }
    );
  }
}

export async function proxyPost(path: string, body?: unknown): Promise<NextResponse> {
  try {
    const res = await backendFetch(path, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "backend unreachable" },
      { status: 502 }
    );
  }
}

export async function proxyPut(path: string, body: unknown): Promise<NextResponse> {
  try {
    const res = await backendFetch(path, { method: "PUT", body: JSON.stringify(body) });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "backend unreachable" },
      { status: 502 }
    );
  }
}
