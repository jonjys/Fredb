import { proxyGet } from "@/lib/backend";

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  return proxyGet(`/api/futures/market/orderbook?${params.toString()}`);
}
